import time
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from decimal import Decimal
from datetime import datetime as dtime
import os
from typing import List

from fastapi import FastAPI, Depends, HTTPException, Query
from octopus.db.models.digests import Digest, DigestStory
from octopus.schemas.digest import DigestResponse, DigestStoryBase
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
    url: str  # Main URL for the story
    target_url: Optional[str]  # Original article URL (if different)
    posted_at: dtime
    user: Optional[str]  # Not all sources may have a user
    latest_vote_count: Optional[int] = None
    summary: Optional[str] = None
    tags: List[TagScore] = []
    entities: List[EntityScore] = []
    source: str  # Where the story came from (e.g., 'hacker_news', 'email', 'telegram')

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
    min_votes: Optional[int] = Query(None, ge=0, description="Minimum number of votes (only for HN)"),
    order_by: Optional[str] = Query(
        None,
        description="Order by field (posted_at_asc, posted_at_desc, votes_asc, votes_desc)"
    ),
    start_date: Optional[dtime] = Query(None, description="Filter stories posted at or after this date (ISO 8601)"),
    end_date: Optional[dtime] = Query(None, description="Filter stories posted at or before this date (ISO 8601)"),
    limit: int = Query(50, ge=1, le=1000, description="Maximum number of stories to return (max 50)"),
    db: Session = Depends(get_session)
) -> List[StoryBrief]:
    """
    Retrieve all stories from all sources with their basic information and the latest vote count (if available).
    """
    try:
        t0 = time.perf_counter()
        # --- HACKER NEWS STORIES ---
        hn_query = (
            select(Story, ProcessedItem)
            .outerjoin(
                ProcessedItem,
                (ProcessedItem.related_item_type == 'hacker_news_story') &
                (ProcessedItem.related_item_id == Story.id)
            )
            .options(
                joinedload(Story.votes),
                joinedload(ProcessedItem.tags).joinedload(ItemTagRelation.tag),
                joinedload(ProcessedItem.entities).joinedload(ItemEntityRelation.entity)
            )
        )
        if start_date is not None:
            hn_query = hn_query.where(Story.posted_at >= start_date)
        if end_date is not None:
            hn_query = hn_query.where(Story.posted_at <= end_date)
        if min_votes is not None:
            latest_votes = select(StoryVotes.story_id, StoryVotes.vote_count).distinct(
                StoryVotes.story_id
            ).order_by(StoryVotes.story_id, StoryVotes.tstamp.desc()).subquery()
            hn_query = hn_query.join(
                latest_votes,
                Story.id == latest_votes.c.story_id
            ).where(latest_votes.c.vote_count >= min_votes)
        if order_by:
            if order_by == 'posted_at_asc':
                hn_query = hn_query.order_by(Story.posted_at.asc())
            elif order_by == 'posted_at_desc':
                hn_query = hn_query.order_by(Story.posted_at.desc())
            elif order_by == 'votes_asc':
                hn_query = hn_query.order_by(latest_votes.c.vote_count.asc())
            elif order_by == 'votes_desc':
                hn_query = hn_query.order_by(latest_votes.c.vote_count.desc())
        hn_query = hn_query.limit(limit)
        hn_results = db.execute(hn_query).unique().all()

        response = []
        # HN
        for story, processed_item in hn_results:
            latest_vote = next(iter(story.votes), None)
            latest_vote_count = latest_vote.vote_count if latest_vote else None
            response.append(StoryBrief(
                id=story.id,
                title=story.title,
                url=f"https://news.ycombinator.com/item?id={story.id}",
                target_url=story.url,
                posted_at=story.posted_at,
                user=story.user,
                latest_vote_count=latest_vote_count,
                summary=processed_item.summary if processed_item else None,
                tags=[TagScore(name=tag_relation.tag.name, score=tag_relation.relation_value) for tag_relation in (processed_item.tags if processed_item else [])],
                entities=[EntityScore(name=entity_relation.entity.name, type=entity_relation.entity.type, score=entity_relation.relation_value, context=entity_relation.context) for entity_relation in (processed_item.entities if processed_item else [])],
                source="hacker_news"
            ))
        t1 = time.perf_counter()
        logger.info(f"get_stories: fetched {len(hn_results)} HN stories in {t1-t0:.3f}s")

        # --- EMAIL STORIES ---
        from octopus.db.models.emails import EmailStory
        email_query = (
            select(EmailStory, ProcessedItem)
            .outerjoin(
                ProcessedItem,
                (ProcessedItem.related_item_type == 'email_story') &
                (ProcessedItem.related_item_id == EmailStory.id)
            )
            .options(
                joinedload(ProcessedItem.tags).joinedload(ItemTagRelation.tag),
                joinedload(ProcessedItem.entities).joinedload(ItemEntityRelation.entity)
            )
        )
        if start_date is not None:
            email_query = email_query.where(EmailStory.discovered_at >= start_date)
        if end_date is not None:
            email_query = email_query.where(EmailStory.discovered_at <= end_date)
        email_query = email_query.order_by(EmailStory.discovered_at.desc()).limit(limit)
        email_results = db.execute(email_query).unique().all()

        # EMAIL
        for story, processed_item in email_results:
            response.append(StoryBrief(
                id=story.id,
                title=story.title,
                url=story.url,
                target_url=story.url,
                posted_at=story.discovered_at,
                user=None,
                latest_vote_count=None,
                summary=processed_item.summary if processed_item else None,
                tags=[TagScore(name=tag_relation.tag.name, score=tag_relation.relation_value) for tag_relation in (processed_item.tags if processed_item else [])],
                entities=[EntityScore(name=entity_relation.entity.name, type=entity_relation.entity.type, score=entity_relation.relation_value, context=entity_relation.context) for entity_relation in (processed_item.entities if processed_item else [])],
                source="email"
            ))
        t2 = time.perf_counter()
        logger.info(f"get_stories: fetched {len(email_results)} email stories in {t2-t1:.3f}s")

        # --- TELEGRAM STORIES ---
        from octopus.db.models.telegram import TelegramStory
        telegram_query = select(TelegramStory)
        if start_date is not None:
            telegram_query = telegram_query.where(TelegramStory.posted_at >= start_date)
        if end_date is not None:
            telegram_query = telegram_query.where(TelegramStory.posted_at <= end_date)
        telegram_query = telegram_query.order_by(TelegramStory.posted_at.desc()).limit(limit)
        telegram_stories = db.execute(telegram_query).unique().scalars().all()
        t3 = time.perf_counter()
        logger.info(f"get_stories: fetched {len(telegram_stories)} telegram stories in {t3-t2:.3f}s")

        # TELEGRAM
        for story in telegram_stories:
            processed_item = story.processed_item
            url = story.urls[0] if story.urls and len(story.urls) > 0 else None
            response.append(StoryBrief(
                id=story.id,
                title=story.content[:100] if story.content else f"Telegram message {story.id}",
                url=url or f"https://t.me/c/{story.channel_id}/{story.message_id}",
                target_url=url,
                posted_at=story.posted_at,
                user=None,
                latest_vote_count=None,
                summary=processed_item.summary if processed_item else None,
                tags=[TagScore(name=tag_relation.tag.name, score=tag_relation.relation_value) for tag_relation in (processed_item.tags if processed_item else [])],
                entities=[EntityScore(name=entity_relation.entity.name, type=entity_relation.entity.type, score=entity_relation.relation_value, context=entity_relation.context) for entity_relation in (processed_item.entities if processed_item else [])],
                source="telegram"
            ))

        t4 = time.perf_counter()
        logger.info(f"get_stories: built response for {len(response)} stories in {t4-t3:.3f}s")
        # Sort all stories by posted_at desc and apply global limit
        response.sort(key=lambda s: s.posted_at, reverse=True)
        t5 = time.perf_counter()
        logger.info(f"get_stories: sorted and limited response in {t5-t4:.3f}s, total time: {t5-t0:.3f}s")
        return response[:limit]
    except SQLAlchemyError as e:
        logger.error(f"Database error in get_stories: {str(e)}")
        raise
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


@app.get("/api/digests", response_model=List[DigestResponse])
async def get_digests(
    start_date: Optional[dtime] = Query(None, description="Filter digests created at or after this date (ISO 8601)"),
    end_date: Optional[dtime] = Query(None, description="Filter digests created at or before this date (ISO 8601)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_session)
) -> List[DigestResponse]:
    """
    Get tech digests with pagination and optional date filtering.

    Args:
        start_date: Filter digests created at or after this date
        end_date: Filter digests created at or before this date
        skip: Number of digests to skip (for pagination)
        limit: Maximum number of digests to return
        db: Database session

    Returns:
        List[DigestResponse]: List of digests with their stories

    Raises:
        HTTPException: If database error occurs
    """
    try:
        query = (
            select(Digest)
            .options(
                joinedload(Digest.stories)
                .joinedload(DigestStory.processed_item)
                .options(
                    joinedload(ProcessedItem.tags).joinedload(ItemTagRelation.tag),
                    joinedload(ProcessedItem.entities).joinedload(ItemEntityRelation.entity)
                )
            )
            .order_by(desc(Digest.created_at))
        )

        if start_date:
            query = query.where(Digest.created_at >= start_date)
        if end_date:
            query = query.where(Digest.created_at <= end_date)

        query = query.offset(skip).limit(limit)
        result = db.execute(query)
        digests = result.unique().scalars().all()

        responses = []
        for digest in digests:
            # Convert each digest to a DigestResponse
            response_data = {
                'id': digest.id,
                'content': digest.content,
                'start_date': digest.start_date,
                'end_date': digest.end_date,
                'created_at': digest.created_at,
                'file_path': digest.file_path,
                'stories': [DigestStoryBase.model_validate(story) for story in digest.stories]
            }
            responses.append(DigestResponse(**response_data))

        return responses

    except SQLAlchemyError as e:
        logger.error(f"Database error in get_digests: {str(e)}")
        raise HTTPException(status_code=500, detail="Database error")


@app.get("/api/digests/{digest_id}", response_model=DigestResponse)
async def get_digest(
    digest_id: int,
    db: Session = Depends(get_session)
) -> DigestResponse:
    """
    Get a specific tech digest by ID.

    Args:
        digest_id: ID of the digest to retrieve
        db: Database session

    Returns:
        DigestResponse: The requested digest with its stories

    Raises:
        HTTPException: If digest not found or database error occurs
    """
    try:
        query = (
            select(Digest)
            .where(Digest.id == digest_id)
            .options(
                joinedload(Digest.stories)
                .joinedload(DigestStory.processed_item)
                .options(
                    joinedload(ProcessedItem.tags).joinedload(ItemTagRelation.tag),
                    joinedload(ProcessedItem.entities).joinedload(ItemEntityRelation.entity)
                )
            )
        )
        result = db.execute(query)
        digest = result.unique().scalar_one_or_none()

        if not digest:
            raise HTTPException(status_code=404, detail="Digest not found")

        return DigestResponse.from_orm(digest)

    except SQLAlchemyError as e:
        logger.error(f"Database error in get_digest: {str(e)}")
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
        Optional[VectorStoreIndex]: The created index, or None if no documents are found
        
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
