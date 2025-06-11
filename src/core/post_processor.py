from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pathlib import Path
import json
import os
from src.utils.logger import logger
import time


class PostProcessor(ABC):
    """Abstract base class for post-processing generated datasets."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    @abstractmethod
    def process(self, output_paths: List[str], base_output_dir: str) -> Optional[str]:
        """
        Process the generated dataset outputs.
        
        Args:
            output_paths: List of paths to generated datasets
            base_output_dir: Base directory for output
            
        Returns:
            Path to the final processed output or None if failed
        """
        pass


class ZipPostProcessor(PostProcessor):
    """Post-processor that creates ZIP archives of datasets."""
    
    def process(self, output_paths: List[str], base_output_dir: str) -> Optional[str]:
        """Create ZIP archive of the datasets."""
        try:
            import zipfile
            from pathlib import Path
            
            base_path = Path(base_output_dir)
            if not base_path.exists():
                logger.error(f"Dataset path not found: {base_path}")
                return None

            # Extract the correct structure name (last part of the path)
            structure_name = base_path.name
            zip_filename = f"{structure_name}.zip"

            # Get output directory from config
            output_dir = self.config.get("directories", {}).get("output", "output_datasets")
            zip_path = os.path.join(output_dir, zip_filename)

            # Create the ZIP file
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(base_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, start=base_path)
                        zipf.write(file_path, arcname)

            logger.info(f"Created ZIP archive: {zip_path}")
            return zip_path
            
        except Exception as e:
            logger.error(f"Error creating ZIP archive: {e}")
            return None


class AggregationPostProcessor(PostProcessor):
    """Post-processor that aggregates datasets into a single file."""
    
    def process(self, output_paths: List[str], base_output_dir: str) -> Optional[str]:
        """Aggregate datasets into a single file."""
        try:
            aggregation_config = self.config.get("dataset_generation", {}).get("aggregation", {})
            
            filename = aggregation_config.get("output_filename", "aggregated_data")
            output_format = self.config.get("dataset_generation", {}).get("output_format", "json")
            merge_strategy = aggregation_config.get("merge_strategy", "combine_arrays")
            include_metadata = aggregation_config.get("include_metadata", True)
            
            # Create aggregated file path
            aggregated_path = Path(base_output_dir) / f"{filename}.{output_format}"
            os.makedirs(base_output_dir, exist_ok=True)
            
            logger.info(f"Aggregating {len(output_paths)} datasets into {aggregated_path}")
            
            if output_format == "json":
                aggregated_data = self._aggregate_json_files(output_paths, merge_strategy, include_metadata)
                with open(aggregated_path, 'w', encoding='utf-8') as f:
                    json.dump(aggregated_data, f, indent=2, ensure_ascii=False)
            else:
                aggregated_content = self._aggregate_text_files(output_paths, include_metadata)
                with open(aggregated_path, 'w', encoding='utf-8') as f:
                    f.write(aggregated_content)
            
            logger.info(f"Successfully created aggregated file: {aggregated_path}")
            return str(aggregated_path)
            
        except Exception as e:
            logger.error(f"Error aggregating datasets: {e}")
            return None
    
    def _aggregate_json_files(self, file_paths: List[str], merge_strategy: str, include_metadata: bool) -> Dict[str, Any]:
        """Aggregate JSON files based on merge strategy."""
        aggregated = {
            "aggregated_data": [],
            "source_files": [],
            "total_items": 0
        }
        
        if include_metadata:
            import time
            aggregated["metadata"] = {
                "aggregation_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "merge_strategy": merge_strategy,
                "source_count": len(file_paths)
            }
        
        for file_path in file_paths:
            try:
                if not os.path.exists(file_path):
                    logger.warning(f"File not found: {file_path}")
                    continue
                
                dataset_dir = Path(file_path)
                json_files = list(dataset_dir.glob("*.json"))
                
                for json_file in json_files:
                    if json_file.name == "metadata.json":
                        continue
                    
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    source_info = {
                        "source_file": str(json_file),
                        "relative_path": str(json_file.relative_to(dataset_dir.parent))
                    }
                    aggregated["source_files"].append(source_info)
                    
                    if merge_strategy == "combine_arrays":
                        if isinstance(data, list):
                            aggregated["aggregated_data"].extend(data)
                            aggregated["total_items"] += len(data)
                        else:
                            aggregated["aggregated_data"].append(data)
                            aggregated["total_items"] += 1
                    elif merge_strategy == "concatenate_objects":
                        file_data = {
                            "source": source_info,
                            "data": data
                        }
                        aggregated["aggregated_data"].append(file_data)
                        aggregated["total_items"] += 1
                        
            except Exception as e:
                logger.error(f"Error processing file {file_path}: {e}")
                continue
        
        return aggregated
    
    def _aggregate_text_files(self, file_paths: List[str], include_metadata: bool) -> str:
        """Aggregate text files by concatenating content."""
        aggregated_content = []
        
        if include_metadata:
            aggregated_content.append(f"# Aggregated Dataset")
            aggregated_content.append(f"# Generated on: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            aggregated_content.append(f"# Source files: {len(file_paths)}")
            aggregated_content.append("")
        
        for file_path in file_paths:
            try:
                if not os.path.exists(file_path):
                    continue
                
                dataset_dir = Path(file_path)
                text_files = list(dataset_dir.glob("*.txt"))
                
                for text_file in text_files:
                    aggregated_content.append(f"## Source: {text_file.name}")
                    aggregated_content.append("")
                    
                    with open(text_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        aggregated_content.append(content)
                    
                    aggregated_content.append("")
                    aggregated_content.append("---")
                    aggregated_content.append("")
                        
            except Exception as e:
                logger.error(f"Error processing text file {file_path}: {e}")
                continue
        
        return "\n".join(aggregated_content)