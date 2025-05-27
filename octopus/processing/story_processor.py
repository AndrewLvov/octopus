import json
import logging
from typing import List, Tuple
import yaml

from octopus.genai.processor import GenAIProcessor
logger = logging.getLogger(__name__)

def _load_prompt() -> str:
    """Load the story analysis prompt from the txt file"""
    prompt_path = "octopus/genai/prompts/story_analysis.txt"
    with open(prompt_path, "r") as f:
        return f.read()

STORY_ANALYSIS_PROMPT = _load_prompt()


class EmptySummaryResult(Exception):
    """Exception raised when a summary result is empty"""
    pass


def clean_yaml(yaml_str: str) -> str:
    """Clean up YAML string by removing invalid characters and code block markers"""
    # Remove code block markers
    yaml_str = yaml_str.strip()
    if yaml_str.startswith("```yaml"):
        yaml_str = yaml_str[7:]
    elif yaml_str.startswith("```"):
        yaml_str = yaml_str[3:]
    if yaml_str.endswith("```"):
        yaml_str = yaml_str[:-3]
    
    # Remove null characters
    yaml_str = yaml_str.replace("\x00", "")
    
    return yaml_str.strip()

class StoryProcessor:
    """Handles story-specific processing using GenAIProcessor"""

    def __init__(self, required_tags: List[str]):
        self.processor = GenAIProcessor()
        self.required_tags = required_tags

    async def process_content(
        self, 
        content: str,
        target_content: str,
        comments: List[str] = None
    ) -> Tuple[str, List[Tuple[str, float]], List[Tuple[str, str, float, str]]]:
        """
        Process story content and comments to generate summary, tags, and entities.

        Args:
            content: The story content to process
            comments: Optional list of comment texts to include in analysis

        Returns:
            Tuple of (summary, list of (tag, score) tuples, list of (name, type, score, context) tuples)
        """
        if not (content or target_content or comments):
            raise EmptySummaryResult("Empty content provided")

        try:
            # Format comments if provided
            comments_text = "\n".join(comments) if comments else "No comments available"
            
            # Process with LLM
            prompt = STORY_ANALYSIS_PROMPT.format(
                story_content=content,
                target_content=target_content,
                comments_content=comments_text
            )
            response = await self.processor.process(prompt)
            
            try:
                result = yaml.safe_load(clean_yaml(response))
            except yaml.YAMLError as e:
                logger.error(f"Invalid YAML response from processor: {str(e)}")
                return "Error: Invalid response format", [(tag, 0.5) for tag in self.required_tags], []

            try:
                # Extract summary and tags
                summary_data = result["summary"]
                # If summary is a dict, get the text content
                summary = summary_data["text"] if isinstance(summary_data, dict) else str(summary_data)
                tags = [(item["name"], float(item["score"])) for item in result["tags"]]
                
                # Extract entities with validation
                entities = []
                valid_types = {"company", "product", "person", "framework"}
                
                for item in result.get("entities", []):
                    name = item.get("name")
                    entity_type = item.get("type")
                    score = item.get("score")
                    context = item.get("context")
                    
                    if not all([name, entity_type, score, context]):
                        logger.warning(f"Skipping entity with missing data: {item}")
                        continue
                        
                    if entity_type not in valid_types:
                        logger.warning(f"Skipping entity with invalid type: {entity_type}")
                        continue
                        
                    try:
                        score = float(score)
                        if not 0 <= score <= 1:
                            logger.warning(f"Skipping entity with invalid score: {score}")
                            continue
                    except (TypeError, ValueError):
                        logger.warning(f"Skipping entity with non-numeric score: {score}")
                        continue
                        
                    entities.append((name, entity_type, score, context))
                
            except (KeyError, ValueError) as e:
                logger.error(f"Missing or invalid data in response: {str(e)}")
                return "Error: Invalid response data", [(tag, 0.5) for tag in self.required_tags], []

            # Ensure required tags are included
            tag_dict = dict(tags)
            for required_tag in self.required_tags:
                if required_tag not in tag_dict:
                    tags.append((required_tag, 0.0))

            return summary, tags, entities

        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Network error while processing content: {str(e)}")
            return f"Error: Network issue while processing", [(tag, 0.5) for tag in self.required_tags], []
