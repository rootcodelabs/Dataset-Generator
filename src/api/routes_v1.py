from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, HTTPException, Depends

from src.core.data_generator import DataGenerator
from src.core.data_source import DataSourceManager
from src.core.post_processor_factory import PostProcessorFactory
from pydantic import BaseModel, Field
from src.utils.logger import logger
import os
import time
from pathlib import Path

router = APIRouter()


class GenerateRequest(BaseModel):
    data_path: str
    output_filename: Optional[str] = None

def get_data_generator(request: Request) -> DataGenerator:
    """
    Get a DataGenerator instance initialized with the application configuration.

    This function serves as a FastAPI dependency that creates and returns a properly
    configured DataGenerator instance using the application's configuration stored
    in request.app.state.config.

    Args:
        request (Request): The FastAPI request object containing application state

    Returns:
        DataGenerator: An initialized data generator instance

    Raises:
        HTTPException: 500 error if application configuration is not found

    Example:
        @router.post("/generate")
        async def generate_dataset(
            request_data: SomeModel,
            data_generator: DataGenerator = Depends(get_data_generator)
        ):
            result = data_generator.generate(...)
            return {"status": "success", "data": result}
    """
    if not hasattr(request.app.state, "config"):
        raise HTTPException(
            status_code=500, detail="Application configuration not found"
        )
    return DataGenerator(request.app.state.config)


@router.post("/generate-bulk")
async def generate_bulk_dataset(
    request: GenerateRequest,
    fastapi_request: Request,
    data_generator: DataGenerator = Depends(get_data_generator),
):
    """
    Generate datasets in bulk by processing multiple data sources.
    
    All configuration parameters are loaded from config.yaml.
    Only data_path needs to be provided by the user.
    Optional output_filename can override the default aggregation filename.
    """
    try:
        logger.info(f"Received bulk generation request for data_path: {request.data_path}")
        if request.output_filename:
            logger.info(f"Using custom output filename: {request.output_filename}")

        # Get all configuration from config file
        config = fastapi_request.app.state.config
        dataset_config = config.get("dataset_generation", {})
        
        # Validate that required config exists
        if not dataset_config:
            raise HTTPException(
                status_code=500, 
                detail="dataset_generation configuration not found in config file"
            )
        
        # Extract all parameters from config
        structure_name = dataset_config.get("structure_name")
        prompt_template_name = dataset_config.get("prompt_template_name")
        traversal_strategy = dataset_config.get("traversal_strategy")
        num_examples = dataset_config.get("num_samples")
        output_format = dataset_config.get("output_format")
        parameters = dataset_config.get("parameters", {})
        filter_config = dataset_config.get("filter", {})
        post_processing_type = dataset_config.get("post_processing", "zip")
        
        # Override output_filename if provided in request
        modified_config = config.copy()
        if request.output_filename:
            # Deep copy the dataset_generation section to avoid modifying original config
            modified_config["dataset_generation"] = dataset_config.copy()
            
            # Ensure aggregation section exists
            if "aggregation" not in modified_config["dataset_generation"]:
                modified_config["dataset_generation"]["aggregation"] = {}
            else:
                modified_config["dataset_generation"]["aggregation"] = dataset_config.get("aggregation", {}).copy()
            
            # Set the dynamic output filename
            modified_config["dataset_generation"]["aggregation"]["output_filename"] = request.output_filename
            logger.info(f"Overriding config output filename with: {request.output_filename}")
        
        # Validate required config values
        required_fields = {
            "structure_name": structure_name,
            "prompt_template_name": prompt_template_name,
            "traversal_strategy": traversal_strategy,
            "num_samples": num_examples,
            "output_format": output_format
        }
        
        missing_fields = [field for field, value in required_fields.items() if not value]
        if missing_fields:
            raise HTTPException(
                status_code=500,
                detail=f"Missing required configuration fields: {missing_fields}"
            )

        data_path = request.data_path
        output_dir = config.get("directories", {}).get("output")

        logger.info(f"Using configuration - Structure: {structure_name}, Template: {prompt_template_name}, Strategy: {traversal_strategy}, Samples: {num_examples}, Post-processing: {post_processing_type}")

        # Create data source manager
        source_manager = DataSourceManager()

        # Load all matching sources
        data_sources = source_manager.load_sources(
            base_path=data_path,
            strategy_name=traversal_strategy,
            filter_config=filter_config,
        )

        if not data_sources:
            return {
                "status": "error",
                "message": f"No data sources found matching the criteria in {data_path}",
            }

        logger.info(f"Found {len(data_sources)} data sources to process")

        # Track all output paths for post-processing
        all_output_paths = []
        results = []

        for source in data_sources:
            # Extract metadata for parameters
            source_params = parameters.copy()

            # Add source metadata to parameters
            if traversal_strategy == "institutional":
                source_params["institution"] = source.metadata.get("institution", "unknown")
                source_params["topic"] = source.metadata.get("topic", "unknown")
                source_params["topic_content"] = source.content
            else:
                # For other traversal strategies, use file path components
                source_params["file_path"] = source.path
                source_params["file_content"] = source.content
                source_params["file_name"] = source.name

                # Add any other metadata from the source
                for key, value in source.metadata.items():
                    if key not in source_params:
                        source_params[key] = value

            # Generate dataset for this source
            timestamp = time.strftime("%Y%m%d_%H%M%S")

            # Determine output path based on metadata
            if traversal_strategy == "institutional":
                institution = source.metadata.get("institution", "unknown")
                topic = source.metadata.get("topic", "unknown")
                output_base_path = f"{output_dir}/{structure_name}/{institution}/{topic}_{timestamp}"
            else:
                # For other traversal strategies, use relative path
                rel_path = source.metadata.get("relative_path", source.name)
                output_base_path = f"{output_dir}/{structure_name}/{rel_path}_{timestamp}"

            logger.info(f"Generating dataset for source: {source.path} -> {output_base_path}")

            # Generate dataset
            result_path = data_generator.generate(
                structure_name=structure_name,
                prompt_template_name=prompt_template_name,
                output_base_path=output_base_path,
                num_examples=num_examples,
                output_format=output_format,
                parameters=source_params,
            )

            all_output_paths.append(result_path)
            results.append({"source": source.path, "output_path": result_path})

        # Generic post-processing using factory pattern with potentially modified config
        base_output_dir = f"{output_dir}/{structure_name}"
        post_processor = PostProcessorFactory.create_post_processor(modified_config)  # Use modified config
        final_output_path = post_processor.process(all_output_paths, base_output_dir)

        if final_output_path:
            logger.info(f"Post-processing completed: {final_output_path}")
            
            # Determine response based on post-processing type
            response_data = {
                "status": "success",
                "message": f"Generated datasets for {len(results)} sources",
                "results": results,
                "post_processing_type": post_processing_type,
                "configuration_used": {
                    "structure_name": structure_name,
                    "prompt_template_name": prompt_template_name,
                    "traversal_strategy": traversal_strategy,
                    "num_examples": num_examples,
                    "output_format": output_format,
                    "post_processing": post_processing_type
                }
            }
            
            # Add custom output filename to response if provided
            if request.output_filename:
                response_data["configuration_used"]["custom_output_filename"] = request.output_filename
            
            # Add appropriate output path field based on post-processing type
            if post_processing_type == "aggregation":
                response_data["aggregated_path"] = final_output_path
            else:
                response_data["zip_path"] = final_output_path
                
            return response_data
        else:
            raise HTTPException(status_code=500, detail="Post-processing failed")
            
    except Exception as e:
        logger.exception(f"Error generating bulk datasets: {str(e)}")
        return {
            "status": "error",
            "message": f"Error generating bulk datasets: {str(e)}",
        }


@router.get("/health")
async def health_check(request: Request):
    """Health check endpoint"""
    provider_name = request.app.state.config.get("provider", {}).get("name", "unknown")

    return {"status": "healthy", "version": "1.0.0", "provider": provider_name}