
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from decimal import Decimal
from datetime import datetime as dtime

from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy import desc
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from dotenv import load_dotenv

from llama_index.core import VectorStoreIndex, Document, SimpleDirectoryReader
from llama_index.vector_stores.postgres import PGVectorStore
from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
from llama_index.llms.azure_openai import AzureOpenAI, AsyncAzureOpenAI

from octopus.db.session import get_session
from octopus.db.models.hacker_news import Story, StoryVotes
from octopus.db.models.summaries import (
    ProcessedItem, ItemTag, ItemTagRelation,
    ItemEntity, ItemEntityRelation
)
from octopus.db.models.prompts import Prompt

logger = logging.getLogger(__name__)
app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins in development
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Load environment variables
load_dotenv()

class PromptResponse(BaseModel):
    id: int
    prompt_text: str
    response_text: str
    response_format: str
    temperature: Optional[str]
    max_tokens: Optional[int]
    created_at: dtime

    class Config:
        from_attributes = True

class TagScore(BaseModel):
    name: str
    score: Decimal

    model_config = {
        "from_attributes": True,
        "json_encoders": {
            Decimal: float
        }
    }

class EntityScore(BaseModel):
    name: str
    type: str
    score: Decimal
    context: Optional[str] = None

    model_config = {
        "from_attributes": True,
        "json_encoders": {
            Decimal: float
        }
    }

class StorySummary(BaseModel):
    id: int
    created_at: dtime
    summary: str
    tags: List[TagScore]
    entities: List[EntityScore]

    class Config:
        from_attributes = True

class VoteHistory(BaseModel):
    timestamp: dtime
    vote_count: int

    class Config:
        from_attributes = True

class StoryBrief(BaseModel):
    id: int
    title: str
    url: str  # HN URL
    target_url: Optional[str]  # Original article URL
    posted_at: dtime
    user: str
    latest_vote_count: Optional[int] = None
    summary: Optional[str] = None
    tags: List[TagScore] = []
    entities: List[EntityScore] = []

    class Config:
        from_attributes = True

class StoryDetailResponse(BaseModel):
    id: int
    title: str
    url: str  # HN URL
    target_url: Optional[str]  # Original article URL
    content: Optional[str]
    target_content: Optional[str]
    posted_at: dtime
    user: str
    vote_history: List[VoteHistory]
    summary: Optional[str] = None
    tags: List[TagScore] = []
    entities: List[EntityScore] = []

    class Config:
        from_attributes = True

@app.get("/api/prompts", response_model=List[PromptResponse])
async def get_prompts(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    response_format: Optional[str] = Query(None),
    db: Session = Depends(get_session)
) -> List[PromptResponse]:
    """
    Retrieve prompts with pagination and optional filtering.
    
    Args:
        skip: Number of prompts to skip (for pagination)
        limit: Maximum number of prompts to return
        response_format: Optional filter by response format (RAW, YAML, JSON)
        db: Database session provided by FastAPI dependency
        
    Returns:
        List[PromptResponse]: List of prompts
        
    Raises:
        HTTPException: If there's a database error
    """
    try:
        query = select(Prompt).order_by(desc(Prompt.created_at))
        
        if response_format:
            query = query.where(Prompt.response_format == response_format)
            
        query = query.offset(skip).limit(limit)
        
        result = db.execute(query)
        prompts = result.scalars().all()
        
        return [PromptResponse.from_orm(prompt) for prompt in prompts]
        
    except SQLAlchemyError as e:
        logger.error(f"Database error in get_prompts: {str(e)}")
        raise HTTPException(status_code=500, detail="Database error")

@app.get("/api/prompts/{prompt_id}", response_model=PromptResponse)
async def get_prompt(
    prompt_id: int,
    db: Session = Depends(get_session)
) -> PromptResponse:
    """
    Retrieve a specific prompt by ID.
    
    Args:
        prompt_id: ID of the prompt to retrieve
        db: Database session provided by FastAPI dependency
        
    Returns:
        PromptResponse: The requested prompt
        
    Raises:
        HTTPException: If prompt not found or database error occurs
    """
    try:
        query = select(Prompt).where(Prompt.id == prompt_id)
        result = db.execute(query)
        prompt = result.scalar_one_or_none()
        
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")
            
        return PromptResponse.from_orm(prompt)
        
    except SQLAlchemyError as e:
        logger.error(f"Database error in get_prompt: {str(e)}")
        raise HTTPException(status_code=500, detail="Database error")


@app.get("/api/stories", response_model=List[StoryBrief])
async def get_stories(
    min_votes: Optional[int] = Query(None, ge=0, description="Minimum number of votes"),
    order_by: Optional[str] = Query(
        None,
        description="Order by field (posted_at_asc, posted_at_desc, votes_asc, votes_desc)"
    ),
    start_date: Optional[dtime] = Query(None, description="Filter stories posted at or after this date (ISO 8601)"),
    end_date: Optional[dtime] = Query(None, description="Filter stories posted at or before this date (ISO 8601)"),
    limit: int = Query(20, ge=1, le=50, description="Maximum number of stories to return (max 50)"),
    db: Session = Depends(get_session)
) -> List[StoryBrief]:
    """
    Retrieve all stories with their basic information and the latest vote count.
    
    Args:
        min_votes: Optional minimum number of votes to filter by
        order_by: Optional field to order results by
        db: Database session provided by FastAPI dependency
        
    Returns:
        List[StoryBrief]: List of stories with their basic information
        
    Raises:
        HTTPException: If there's a database error
    """
    try:
        # Base query joining stories with their summaries
        query = (
            select(Story)
            .outerjoin(
                ProcessedItem,
                (ProcessedItem.related_item_type == 'hacker_news_story') &
                (ProcessedItem.related_item_id == Story.id)
            )
            .options(joinedload(Story.votes))
        )

        # Apply minimum votes filter if specified
        if min_votes is not None:
            latest_votes = select(StoryVotes.story_id, StoryVotes.vote_count).distinct(
                StoryVotes.story_id
            ).order_by(StoryVotes.story_id, StoryVotes.tstamp.desc()).subquery()
            
            query = query.join(
                latest_votes,
                Story.id == latest_votes.c.story_id
            ).where(latest_votes.c.vote_count >= min_votes)

        # Apply date filters if specified
        if start_date is not None:
            query = query.where(Story.posted_at >= start_date)
        if end_date is not None:
            query = query.where(Story.posted_at <= end_date)

        # Apply ordering
        if order_by:
            if order_by == 'posted_at_asc':
                query = query.order_by(Story.posted_at.asc())
            elif order_by == 'posted_at_desc':
                query = query.order_by(Story.posted_at.desc())
            elif order_by == 'votes_asc':
                query = query.order_by(latest_votes.c.vote_count.asc())
            elif order_by == 'votes_desc':
                query = query.order_by(latest_votes.c.vote_count.desc())

        query = query.limit(limit)
        result = db.execute(query)
        stories = result.unique().scalars().all()
        
        # Format response with vote history, summary and tags
        response = []
        for story in stories:
            # Query summary and tags for the story
            summary_query = (
                select(ProcessedItem)
                .where(
                    ProcessedItem.related_item_type == 'hacker_news_story',
                    ProcessedItem.related_item_id == story.id
                )
                .options(
                    joinedload(ProcessedItem.tags).joinedload(ItemTagRelation.tag),
                    joinedload(ProcessedItem.entities).joinedload(ItemEntityRelation.entity)
                )
            )
            summary_result = db.execute(summary_query)
            processed_item = summary_result.unique().scalar_one_or_none()

            # Get latest vote count
            latest_vote = next(iter(story.votes), None)
            latest_vote_count = latest_vote.vote_count if latest_vote else None

            # Convert to response format
            story_response = StoryBrief(
                id=story.id,
                title=story.title,
                url=f"https://news.ycombinator.com/item?id={story.id}",
                target_url=story.url,
                posted_at=story.posted_at,
                user=story.user,
                latest_vote_count=latest_vote_count,
                summary=processed_item.summary if processed_item else None,
                tags=[
                    TagScore(
                        name=tag_relation.tag.name,
                        score=tag_relation.relation_value
                    )
                    for tag_relation in (processed_item.tags if processed_item else [])
                ],
                entities=[
                    EntityScore(
                        name=entity_relation.entity.name,
                        type=entity_relation.entity.type,
                        score=entity_relation.relation_value,
                        context=entity_relation.context
                    )
                    for entity_relation in (processed_item.entities if processed_item else [])
                ]
            )
            response.append(story_response)

        return response
        
    except SQLAlchemyError as e:
        logger.error(f"Database error in get_stories: {str(e)}")
        raise HTTPException(status_code=500, detail="Database error")

@app.get("/api/stories/{story_id}", response_model=StoryDetailResponse)
async def get_story(
    story_id: int,
    db: Session = Depends(get_session)
) -> StoryDetailResponse:
    """
    Retrieve detailed information for a specific story.
    
    Args:
        story_id: ID of the story to get
        db: Database session provided by FastAPI dependency
        
    Returns:
        StoryDetailResponse: Detailed story information including vote history
        
    Raises:
        HTTPException: If story not found or database error occurs
    """
    try:
        # Query the story with its votes and processed item
        query = (
            select(Story)
            .where(Story.id == story_id)
            .options(
                joinedload(Story.votes),
                joinedload(Story.comments)
            )
        )
        result = db.execute(query)
        story = result.unique().scalar_one_or_none()
        
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")

        # Query summary and tags for the story
        summary_query = (
            select(ProcessedItem)
            .where(
                ProcessedItem.related_item_type == 'hacker_news_story',
                ProcessedItem.related_item_id == story.id
            )
            .options(
                joinedload(ProcessedItem.tags).joinedload(ItemTagRelation.tag),
                joinedload(ProcessedItem.entities).joinedload(ItemEntityRelation.entity)
            )
        )
        summary_result = db.execute(summary_query)
        processed_item = summary_result.unique().scalar_one_or_none()

        return StoryDetailResponse(
            id=story.id,
            title=story.title,
            url=f"https://news.ycombinator.com/item?id={story.id}",
            target_url=story.url,
            content=story.content,
            target_content=story.target_content,
            posted_at=story.posted_at,
            user=story.user,
            vote_history=[
                VoteHistory(timestamp=vote.tstamp, vote_count=vote.vote_count)
                for vote in story.votes
            ],
            summary=processed_item.summary if processed_item else None,
            tags=[
                TagScore(
                    name=tag_relation.tag.name,
                    score=tag_relation.relation_value
                )
                for tag_relation in (processed_item.tags if processed_item else [])
            ],
            entities=[
                EntityScore(
                    name=entity_relation.entity.name,
                    type=entity_relation.entity.type,
                    score=entity_relation.relation_value,
                    context=entity_relation.context
                )
                for entity_relation in (processed_item.entities if processed_item else [])
            ]
        )
        
    except SQLAlchemyError as e:
        logger.error(f"Database error in get_story: {str(e)}")
        raise HTTPException(status_code=500, detail="Database error")


def init_vector_store() -> tuple[AzureOpenAI, PGVectorStore, AzureOpenAIEmbedding]:
    """
    Initialize and return vector store components.
    
    Returns:
        tuple: (LLM model, Vector store, Embedding model)
        
    Raises:
        ValueError: If required environment variables are missing
        ConnectionError: If vector store connection fails
    """
    required_env_vars = [
        'AZURE_OPENAI_DEPLOYMENT_NAME',
        'AZURE_OPENAI_API_KEY',
        'AZURE_OPENAI_ENDPOINT',
        'AZURE_OPENAI_VERSION',
        'VECTOR_DB_URL',
        'VECTOR_DB_ASYNC_URL',
        'EMBEDDING_DIM',
        'AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME'
    ]
    
    missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    try:
        llm = AzureOpenAI(
            deployment_name=os.environ['AZURE_OPENAI_DEPLOYMENT_NAME'],
            api_key=os.environ['AZURE_OPENAI_API_KEY'],
            azure_endpoint=os.environ['AZURE_OPENAI_ENDPOINT'],
            api_version=os.environ['AZURE_OPENAI_VERSION'],
            model=os.environ['AZURE_OPENAI_DEPLOYMENT_NAME'],
        )
        # self._llm = AzureOpenAI(
        #     api_key=s.AZURE_OPENAI_API_KEY,
        #     azure_endpoint=s.AZURE_OPENAI_ENDPOINT,
        #     api_version=s.AZURE_OPENAI_VERSION,
        #     azure_deployment=model,  # For Azure, model name is the deployment name
        #     model=s.LLM_MODEL,
        # )

        vector_db = PGVectorStore(
            connection_string=os.environ['VECTOR_DB_URL'],
            table_name="llm_vector_store",
            schema_name="llm",
            async_connection_string=os.environ['VECTOR_DB_ASYNC_URL'],
            initialization_fail_on_error=True,
            embed_dim=int(os.environ['EMBEDDING_DIM']),
        )

        embed_model = AzureOpenAIEmbedding(
            azure_endpoint=os.environ['AZURE_OPENAI_ENDPOINT'],
            azure_deployment=None,
            deployment_name=os.environ['AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME'],
            api_key=os.environ['AZURE_OPENAI_API_KEY'],
            api_version="2023-05-15",
        )

        return llm, vector_db, embed_model
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid configuration value: {str(e)}")
        raise ValueError(f"Configuration error: {str(e)}")
    except (ConnectionError, TimeoutError) as e:
        logger.error(f"Connection error initializing vector store: {str(e)}")
        raise ConnectionError(f"Failed to connect to services: {str(e)}")
    except RuntimeError as e:
        logger.error(f"Runtime error initializing vector store: {str(e)}")
        raise RuntimeError(f"Initialization failed: {str(e)}")

def load_and_index_documents(
    vector_store: PGVectorStore,
    embed_model: AzureOpenAIEmbedding,
    llm: AzureOpenAI
) -> Optional[VectorStoreIndex]:
    """
    Load documents from data/documents directory and index them.
    
    Args:
        vector_store: Initialized vector store
        embed_model: Embedding model for document processing
        llm: Language model for document processing
        
    Returns:
        Optional[VectorStoreIndex]: The created index, or None if no documents found
        
    Raises:
        FileNotFoundError: If the documents directory doesn't exist
        IOError: If there's an error reading the documents
    """
    documents_dir = Path("data/documents")
    if not documents_dir.exists():
        raise FileNotFoundError(f"Directory {documents_dir} does not exist")
    
    try:
        documents = SimpleDirectoryReader(
            input_dir=str(documents_dir)
        ).load_data()
        
        if not documents:
            logger.warning("No documents found in data/documents directory")
            return None
        
        try:
            index = VectorStoreIndex.from_documents(
                documents,
                vector_store=vector_store,
                embed_model=embed_model,
                llm=llm,
            )
            
            logger.info(f"Successfully indexed {len(documents)} documents")
            return index
            
        except (ValueError, RuntimeError) as e:
            logger.error(f"Failed to create vector index: {str(e)}")
            raise
            
    except (IOError, RuntimeError) as e:
        logger.error(f"Failed to load documents: {str(e)}")
        raise IOError(f"Error reading documents: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)
    except OSError as e:
        logger.error(f"Failed to start server (port may be in use): {str(e)}")
        raise
    except RuntimeError as e:
        logger.error(f"Server runtime error: {str(e)}")
        raise
