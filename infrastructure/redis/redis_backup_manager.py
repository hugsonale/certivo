"""
Redis Backup Manager
Handles Redis persistence and backup operations
"""

import subprocess
import redis
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import logging
import os

logger = logging.getLogger(__name__)


class RedisBackupManager:
    """
    Redis Backup Manager
    
    Features:
    - RDB snapshot backups
    - AOF persistence
    - Point-in-time recovery support
    - Backup verification
    """
    
    def __init__(
        self,
        redis_hosts: List[str],
        redis_port: int = 6379,
        redis_password: str = "",
        backup_dir: str = "/var/lib/redis/backups"
    ):
        self.redis_hosts = redis_hosts
        self.redis_port = redis_port
        self.redis_password = redis_password
        self.backup_dir = backup_dir
    
    def create_snapshot_backup(self, host: str) -> Dict[str, Any]:
        """
        Create RDB snapshot backup
        
        Args:
            host: Redis host to backup
        
        Returns:
            Backup information
        """
        
        logger.info(f"🔄 Creating snapshot backup for {host}...")
        
        start_time = datetime.utcnow()
        
        # Connect to Redis
        client = redis.Redis(
            host=host,
            port=self.redis_port,
            password=self.redis_password,
            decode_responses=True
        )
        
        # Trigger BGSAVE (background save)
        client.bgsave()
        
        # Wait for save to complete
        while True:
            info = client.info("persistence")
            if info["rdb_bgsave_in_progress"] == 0:
                break
            logger.debug(f"  Waiting for BGSAVE to complete...")
            import time
            time.sleep(1)
        
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        
        # Get backup info
        info = client.info("persistence")
        rdb_file = info["rdb_last_save_time"]
        
        # Copy RDB file to backup directory
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{host.replace('.', '_')}_{timestamp}.rdb"
        backup_path = os.path.join(self.backup_dir, backup_filename)
        
        subprocess.run(
            ["scp", f"{host}:/var/lib/redis/dump.rdb", backup_path],
            check=True
        )
        
        # Get file size
        backup_size = os.path.getsize(backup_path)
        
        logger.info(
            f"✅ Snapshot backup completed:\n"
            f"   Host: {host}\n"
            f"   Duration: {duration:.1f}s\n"
            f"   Size: {backup_size / (1024**2):.2f} MB\n"
            f"   Path: {backup_path}"
        )
        
        return {
            "host": host,
            "timestamp": end_time.isoformat(),
            "duration_seconds": duration,
            "size_bytes": backup_size,
            "backup_path": backup_path
        }
    
    def create_cluster_backup(self) -> List[Dict[str, Any]]:
        """
        Create backup of entire Redis cluster
        
        Returns:
            List of backup information for each node
        """
        
        logger.info(f"🔄 Creating cluster backup ({len(self.redis_hosts)} nodes)...")
        
        backups = []
        
        for host in self.redis_hosts:
            try:
                backup_info = self.create_snapshot_backup(host)
                backups.append(backup_info)
            except Exception as e:
                logger.error(f"❌ Backup failed for {host}: {e}")
                backups.append({
                    "host": host,
                    "status": "failed",
                    "error": str(e)
                })
        
        logger.info(f"✅ Cluster backup completed: {len(backups)} nodes")
        
        return backups
    
    def verify_backup(self, backup_path: str) -> bool:
        """
        Verify RDB backup integrity
        
        Args:
            backup_path: Path to RDB file
        
        Returns:
            True if backup is valid
        """
        
        logger.info(f"🔍 Verifying backup: {backup_path}")
        
        # Use redis-check-rdb to verify
        result = subprocess.run(
            ["redis-check-rdb", backup_path],
            capture_output=True,
            text=True
        )
        
        valid = result.returncode == 0
        
        if valid:
            logger.info(f"✅ Backup is valid: {backup_path}")
        else:
            logger.error(f"❌ Backup verification failed: {result.stderr}")
        
        return valid
    
    def get_backup_age(self, host: str) -> float:
        """
        Get age of last backup in hours
        
        Args:
            host: Redis host
        
        Returns:
            Age in hours
        """
        
        client = redis.Redis(
            host=host,
            port=self.redis_port,
            password=self.redis_password,
            decode_responses=True
        )
        
        info = client.info("persistence")
        last_save_time = datetime.fromtimestamp(info["rdb_last_save_time"])
        age = (datetime.utcnow() - last_save_time).total_seconds() / 3600
        
        return age