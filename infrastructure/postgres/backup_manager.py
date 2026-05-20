"""
PostgreSQL Backup Manager
Handles backup operations, verification, and restore
"""

import subprocess
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class BackupInfo:
    """Backup information"""
    backup_id: str
    backup_type: str  # full, differential, incremental
    timestamp: datetime
    size_bytes: int
    database_size_bytes: int
    wal_start: str
    wal_stop: str
    duration_seconds: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "backup_type": self.backup_type,
            "timestamp": self.timestamp.isoformat(),
            "size_bytes": self.size_bytes,
            "database_size_bytes": self.database_size_bytes,
            "wal_start": self.wal_start,
            "wal_stop": self.wal_stop,
            "duration_seconds": self.duration_seconds
        }


class PostgresBackupManager:
    """
    PostgreSQL Backup Manager
    
    Features:
    - Full, differential, and incremental backups
    - Point-in-time recovery (PITR)
    - Backup verification
    - Restore operations
    - Backup retention management
    
    Recovery Objectives:
    - RPO: 15 minutes (continuous WAL archiving)
    - RTO: 60 minutes (automated restore process)
    """
    
    def __init__(
        self,
        stanza: str = "certivo",
        backup_bucket: str = "certivo-postgres-backups"
    ):
        self.stanza = stanza
        self.backup_bucket = backup_bucket
    
    def create_full_backup(self) -> BackupInfo:
        """
        Create full backup
        
        Returns:
            Backup information
        """
        
        logger.info("🔄 Starting full backup...")
        
        start_time = datetime.utcnow()
        
        # Execute pgBackRest full backup
        result = subprocess.run(
            [
                "pgbackrest",
                "--stanza", self.stanza,
                "--type=full",
                "backup"
            ],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logger.error(f"Backup failed: {result.stderr}")
            raise RuntimeError(f"Backup failed: {result.stderr}")
        
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        
        # Get backup info
        backup_info = self._get_latest_backup_info()
        
        logger.info(
            f"✅ Full backup completed:\n"
            f"   Backup ID: {backup_info.backup_id}\n"
            f"   Duration: {duration:.1f}s\n"
            f"   Size: {backup_info.size_bytes / (1024**3):.2f} GB"
        )
        
        return backup_info
    
    def create_incremental_backup(self) -> BackupInfo:
        """
        Create incremental backup
        
        Returns:
            Backup information
        """
        
        logger.info("🔄 Starting incremental backup...")
        
        start_time = datetime.utcnow()
        
        result = subprocess.run(
            [
                "pgbackrest",
                "--stanza", self.stanza,
                "--type=incr",
                "backup"
            ],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logger.error(f"Incremental backup failed: {result.stderr}")
            raise RuntimeError(f"Incremental backup failed: {result.stderr}")
        
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        
        backup_info = self._get_latest_backup_info()
        
        logger.info(
            f"✅ Incremental backup completed:\n"
            f"   Backup ID: {backup_info.backup_id}\n"
            f"   Duration: {duration:.1f}s"
        )
        
        return backup_info
    
    def _get_latest_backup_info(self) -> BackupInfo:
        """Get information about latest backup"""
        
        result = subprocess.run(
            [
                "pgbackrest",
                "--stanza", self.stanza,
                "--output=json",
                "info"
            ],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Failed to get backup info: {result.stderr}")
        
        info = json.loads(result.stdout)
        latest_backup = info[0]["backup"][-1]
        
        return BackupInfo(
            backup_id=latest_backup["label"],
            backup_type=latest_backup["type"],
            timestamp=datetime.fromtimestamp(latest_backup["timestamp"]["stop"]),
            size_bytes=latest_backup["info"]["size"],
            database_size_bytes=latest_backup["info"]["delta"],
            wal_start=latest_backup["archive"]["start"],
            wal_stop=latest_backup["archive"]["stop"],
            duration_seconds=latest_backup["timestamp"]["stop"] - latest_backup["timestamp"]["start"]
        )
    
    def list_backups(self) -> List[BackupInfo]:
        """
        List all available backups
        
        Returns:
            List of backup information
        """
        
        result = subprocess.run(
            [
                "pgbackrest",
                "--stanza", self.stanza,
                "--output=json",
                "info"
            ],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Failed to list backups: {result.stderr}")
        
        info = json.loads(result.stdout)
        backups = []
        
        for backup_data in info[0]["backup"]:
            backups.append(BackupInfo(
                backup_id=backup_data["label"],
                backup_type=backup_data["type"],
                timestamp=datetime.fromtimestamp(backup_data["timestamp"]["stop"]),
                size_bytes=backup_data["info"]["size"],
                database_size_bytes=backup_data["info"]["delta"],
                wal_start=backup_data["archive"]["start"],
                wal_stop=backup_data["archive"]["stop"],
                duration_seconds=backup_data["timestamp"]["stop"] - backup_data["timestamp"]["start"]
            ))
        
        return backups
    
    def restore_to_point_in_time(
        self,
        target_time: datetime,
        target_dir: str = "/var/lib/postgresql/15/main"
    ) -> bool:
        """
        Restore database to specific point in time (PITR)
        
        Args:
            target_time: Point in time to restore to
            target_dir: Target directory for restore
        
        Returns:
            True if successful
        """
        
        logger.info(
            f"🔄 Starting point-in-time restore:\n"
            f"   Target Time: {target_time.isoformat()}\n"
            f"   Target Dir: {target_dir}"
        )
        
        # Stop PostgreSQL
        subprocess.run(["systemctl", "stop", "postgresql"], check=True)
        
        # Clear data directory
        subprocess.run(["rm", "-rf", f"{target_dir}/*"], shell=True, check=True)
        
        # Restore with PITR
        result = subprocess.run(
            [
                "pgbackrest",
                "--stanza", self.stanza,
                f"--pg1-path={target_dir}",
                "--type=time",
                f"--target={target_time.strftime('%Y-%m-%d %H:%M:%S')}",
                "--target-action=promote",
                "restore"
            ],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logger.error(f"Restore failed: {result.stderr}")
            return False
        
        # Start PostgreSQL
        subprocess.run(["systemctl", "start", "postgresql"], check=True)
        
        logger.info("✅ Point-in-time restore completed successfully")
        
        return True
    
    def restore_from_backup(
        self,
        backup_id: Optional[str] = None,
        target_dir: str = "/var/lib/postgresql/15/main"
    ) -> bool:
        """
        Restore database from specific backup
        
        Args:
            backup_id: Backup ID to restore from (latest if None)
            target_dir: Target directory for restore
        
        Returns:
            True if successful
        """
        
        logger.info(
            f"🔄 Starting restore:\n"
            f"   Backup ID: {backup_id or 'latest'}\n"
            f"   Target Dir: {target_dir}"
        )
        
        # Stop PostgreSQL
        subprocess.run(["systemctl", "stop", "postgresql"], check=True)
        
        # Clear data directory
        subprocess.run(["rm", "-rf", f"{target_dir}/*"], shell=True, check=True)
        
        # Build restore command
        cmd = [
            "pgbackrest",
            "--stanza", self.stanza,
            f"--pg1-path={target_dir}"
        ]
        
        if backup_id:
            cmd.extend(["--set", backup_id])
        
        cmd.append("restore")
        
        # Execute restore
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logger.error(f"Restore failed: {result.stderr}")
            return False
        
        # Start PostgreSQL
        subprocess.run(["systemctl", "start", "postgresql"], check=True)
        
        logger.info("✅ Restore completed successfully")
        
        return True
    
    def verify_backup(self, backup_id: str) -> bool:
        """
        Verify backup integrity
        
        Args:
            backup_id: Backup ID to verify
        
        Returns:
            True if backup is valid
        """
        
        logger.info(f"🔍 Verifying backup: {backup_id}")
        
        result = subprocess.run(
            [
                "pgbackrest",
                "--stanza", self.stanza,
                "--set", backup_id,
                "verify"
            ],
            capture_output=True,
            text=True
        )
        
        success = result.returncode == 0
        
        if success:
            logger.info(f"✅ Backup {backup_id} is valid")
        else:
            logger.error(f"❌ Backup {backup_id} verification failed: {result.stderr}")
        
        return success
    
    def get_rpo_status(self) -> Dict[str, Any]:
        """
        Get Recovery Point Objective (RPO) status
        
        Returns:
            RPO status information
        """
        
        # Get latest WAL archive time
        result = subprocess.run(
            [
                "pgbackrest",
                "--stanza", self.stanza,
                "--output=json",
                "info"
            ],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            return {"status": "error", "message": result.stderr}
        
        info = json.loads(result.stdout)
        latest_backup = info[0]["backup"][-1]
        
        backup_time = datetime.fromtimestamp(latest_backup["timestamp"]["stop"])
        current_time = datetime.utcnow()
        time_since_backup = (current_time - backup_time).total_seconds() / 60
        
        # Check WAL archiving lag
        result = subprocess.run(
            ["psql", "-U", "postgres", "-t", "-c",
             "SELECT EXTRACT(EPOCH FROM (NOW() - pg_last_xact_replay_timestamp())) / 60;"],
            capture_output=True,
            text=True
        )
        
        wal_lag_minutes = float(result.stdout.strip()) if result.returncode == 0 else 0
        
        # RPO target: 15 minutes
        rpo_target_minutes = 15
        rpo_met = wal_lag_minutes <= rpo_target_minutes
        
        return {
            "status": "healthy" if rpo_met else "at_risk",
            "rpo_target_minutes": rpo_target_minutes,
            "actual_rpo_minutes": wal_lag_minutes,
            "last_backup_time": backup_time.isoformat(),
            "time_since_backup_minutes": time_since_backup,
            "wal_archiving_lag_minutes": wal_lag_minutes
        }
    
    def estimate_rto(self, backup_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Estimate Recovery Time Objective (RTO)
        
        Args:
            backup_id: Backup to estimate RTO for (latest if None)
        
        Returns:
            RTO estimation
        """
        
        if not backup_id:
            backups = self.list_backups()
            if not backups:
                return {"status": "error", "message": "No backups available"}
            backup_id = backups[-1].backup_id
        
        # Get backup size
        backups = self.list_backups()
        backup = next((b for b in backups if b.backup_id == backup_id), None)
        
        if not backup:
            return {"status": "error", "message": f"Backup {backup_id} not found"}
        
        # Estimate restore time based on backup size
        # Typical restore speed: ~100 MB/s
        restore_speed_mbps = 100
        backup_size_mb = backup.database_size_bytes / (1024 ** 2)
        estimated_restore_seconds = backup_size_mb / restore_speed_mbps
        
        # Add overhead for PostgreSQL startup, validation, etc. (~5 minutes)
        overhead_seconds = 300
        total_rto_seconds = estimated_restore_seconds + overhead_seconds
        total_rto_minutes = total_rto_seconds / 60
        
        # RTO target: 60 minutes
        rto_target_minutes = 60
        rto_met = total_rto_minutes <= rto_target_minutes
        
        return {
            "status": "healthy" if rto_met else "at_risk",
            "rto_target_minutes": rto_target_minutes,
            "estimated_rto_minutes": total_rto_minutes,
            "backup_id": backup_id,
            "backup_size_gb": backup.database_size_bytes / (1024 ** 3),
            "estimated_restore_seconds": estimated_restore_seconds,
            "overhead_seconds": overhead_seconds
        }