from typing import Dict, Any
from src.core.post_processor import PostProcessor, ZipPostProcessor, AggregationPostProcessor


class PostProcessorFactory:
    """Factory for creating post-processors based on configuration."""
    
    @staticmethod
    def create_post_processor(config: Dict[str, Any]) -> PostProcessor:
        """
        Create appropriate post-processor based on configuration.
        
        Args:
            config: Application configuration
            
        Returns:
            PostProcessor instance
        """
        dataset_config = config.get("dataset_generation", {})
        post_processing_type = dataset_config.get("post_processing", "zip")
        
        if post_processing_type == "aggregation":
            return AggregationPostProcessor(config)
        else:
            return ZipPostProcessor(config)