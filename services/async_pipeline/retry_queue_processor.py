"""
Retry Queue Processor
Moves jobs from retry queue back to primary queue when ready
"""

import asyncio
import asyncpg
import redis.asyncio as redis
import logging
import signal
import sys
import os

sys.path.insert(0, 'services/shared')

from pipeline_orchestrator import AsyncPipelineOrchestrator

logger = logging.getLogger(__name__)


class RetryQueueProcessor:
    """
    Retry Queue Processor
    
    Runs continuously and moves jobs from retry queue
    to primary queue when their backoff period expires
    """
    
    def __init__(self, orchestrator: AsyncPipelineOrchestrator):
        self.orchestrator = orchestrator
        self.running = False
    
    async def start(self, interval_seconds: int = 10):
        """
        Start retry queue processor
        
        Args:
            interval_seconds: How often to check retry queue
        """
        
        self.running = True
        
        # Register signal handlers
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
        
        logger.info(
            f"🔄 Retry Queue Processor starting\n"
            f"   Check Interval: {interval_seconds}s"
        )
        
        while self.running:
            try:
                # Process retry queue
                await self.orchestrator.process_retry_queue()
                
                # Wait before next check
                await asyncio.sleep(interval_seconds)
                
            except Exception as e:
                logger.error(f"❌ Retry queue processor error: {e}")
                await asyncio.sleep(interval_seconds)
        
        logger.info("🛑 Retry Queue Processor stopped")
    
    def _handle_shutdown(self, signum, frame):
        """Handle graceful shutdown"""
        logger.info("🛑 Retry Queue Processor received shutdown signal")
        self.running = False


async def run_retry_processor(
    postgres_dsn: str,
    redis_url: str,
    s3_bucket: str,
    aws_region: str = "us-east-1",
    interval_seconds: int = 10
):
    """
    Run retry queue processor
    
    Args:
        postgres_dsn: PostgreSQL connection string
        redis_url: Redis connection URL
        s3_bucket: S3 bucket name
        aws_region: AWS region
        interval_seconds: Check interval
    """
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create connections
    postgres_pool = await asyncpg.create_pool(postgres_dsn, min_size=2, max_size=5)
    redis_client = await redis.from_url(redis_url)
    
    # Create orchestrator
    orchestrator = AsyncPipelineOrchestrator(
        postgres_pool=postgres_pool,
        redis_client=redis_client,
        s3_bucket=s3_bucket,
        aws_region=aws_region
    )
    
    # Create and start processor
    processor = RetryQueueProcessor(orchestrator)
    
    try:
        await processor.start(interval_seconds)
    finally:
        await postgres_pool.close()
        await redis_client.close()


if __name__ == "__main__":
    asyncio.run(run_retry_processor(
        postgres_dsn=os.getenv("POSTGRES_DSN", "postgresql://certivo:certivo@localhost:5432/certivo"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
        s3_bucket=os.getenv("S3_BUCKET", "certivo-videos-dev"),
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        interval_seconds=int(os.getenv("RETRY_INTERVAL", "10"))
    ))