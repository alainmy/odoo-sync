"""
Task log repository.

Handles Celery task log database operations.
"""
from typing import Optional, List, Dict
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.admin import CeleryTaskLog


class TaskLogRepository:
    """Repository for Celery task log operations."""
    
    def __init__(self, db: Session):
        """
        Initialize repository with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
    
    def create_task_log(
        self,
        task_id: str,
        task_name: str,
        instance_id: int,
        task_args: List = None,
        task_kwargs: Dict = None,
        status: str = "pending",
        parent_task_id: str = None
    ) -> CeleryTaskLog:
        """
        Create a Celery task log record.
        
        Args:
            task_id: Unique Celery task ID
            task_name: Name of the task
            instance_id: WooCommerce instance ID
            task_args: Positional arguments passed to task
            task_kwargs: Keyword arguments passed to task
            status: Initial task status (default: "pending")
            parent_task_id: ID of the parent task if this is a child task
            
        Returns:
            Created CeleryTaskLog record
        """
        log = CeleryTaskLog(
            task_id=task_id,
            task_name=task_name,
            instance_id=instance_id,
            parent_task_id=parent_task_id,
            task_args=task_args or [],
            task_kwargs=task_kwargs or {},
            status=status
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log
    
    def get_task_log(self, task_id: str) -> Optional[CeleryTaskLog]:
        """
        Get task log by task ID.
        
        Args:
            task_id: Celery task ID
            
        Returns:
            CeleryTaskLog record or None
        """
        return self.db.query(CeleryTaskLog).filter(
            CeleryTaskLog.task_id == task_id
        ).first()
    
    def update_task_log(
        self,
        task_id: str,
        status: Optional[str] = None,
        result: Optional[Dict] = None,
        error_message: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None
    ) -> Optional[CeleryTaskLog]:
        """
        Update task log record.
        
        Args:
            task_id: Celery task ID
            status: New task status
            result: Task result dictionary
            error_message: Error message if task failed
            started_at: Task start timestamp
            completed_at: Task completion timestamp
            
        Returns:
            Updated CeleryTaskLog record or None
        """
        log = self.get_task_log(task_id)
        if log.parent_task_id:
            parent = self.db.query(CeleryTaskLog).filter(
                CeleryTaskLog.task_id == log.parent_task_id
            ).first()
            
            # Only process parent if it exists
            if parent:
                logs = self.db.query(CeleryTaskLog).filter(
                    CeleryTaskLog.task_id != task_id,
                    CeleryTaskLog.parent_task_id == parent.task_id
                ).all()
                succesfull = False
                for l in logs:
                    succesfull = True if l.status == "success" else False
                if succesfull and status == "success":
                    parent.status = "success"
                    self.db.commit()
                    self.db.refresh(parent)
        if log:
            if status:
                log.status = status
            if result:
                log.result = result
            if error_message:
                log.error_message = error_message
            if started_at:
                log.started_at = started_at
            if completed_at:
                log.completed_at = completed_at
            self.db.commit()
            self.db.refresh(log)
        return log
    
    def get_task_logs(
        self,
        instance_id: int,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
        task_name: Optional[str] = None
    ) -> List[CeleryTaskLog]:
        """
        Get task logs with filters.
        
        Args:
            instance_id: WooCommerce instance ID
            limit: Maximum number of records
            offset: Number of records to skip
            status: Filter by status
            task_name: Filter by task name
            
        Returns:
            List of CeleryTaskLog records
        """
        query = self.db.query(CeleryTaskLog).filter(
            CeleryTaskLog.instance_id == instance_id
        )
        
        if status:
            query = query.filter(CeleryTaskLog.status == status)
        if task_name:
            query = query.filter(CeleryTaskLog.task_name == task_name)
        
        return query.order_by(
            CeleryTaskLog.id.desc()
        ).offset(offset).limit(limit).all()
    
    def get_child_tasks(self, parent_task_id: str) -> List[CeleryTaskLog]:
        """
        Get all child tasks for a given parent task.
        
        Args:
            parent_task_id: ID of the parent task
            
        Returns:
            List of CeleryTaskLog records that are children of the parent
        """
        return self.db.query(CeleryTaskLog).filter(
            CeleryTaskLog.parent_task_id == parent_task_id
        ).order_by(CeleryTaskLog.created_at).all()
    
    def get_child_tasks_summary(self, parent_task_id: str) -> Dict:
        """
        Get a summary of child task statuses for a parent task.
        
        Args:
            parent_task_id: ID of the parent task
            
        Returns:
            Dict with counts by status: {"total": 10, "pending": 2, "started": 3, ...}
        """
        children = self.get_child_tasks(parent_task_id)
        
        summary = {
            "total": len(children),
            "pending": 0,
            "started": 0,
            "retry": 0,
            "success": 0,
            "failure": 0
        }
        
        for child in children:
            status = child.status
            if status in summary:
                summary[status] += 1
        
        return summary
    
    def get_child_tasks(self, parent_task_id: str) -> List[CeleryTaskLog]:
        """
        Get all child tasks for a given parent task.
        
        Args:
            parent_task_id: ID of the parent task
            
        Returns:
            List of CeleryTaskLog records that are children of the parent
        """
        return self.db.query(CeleryTaskLog).filter(
            CeleryTaskLog.parent_task_id == parent_task_id
        ).order_by(CeleryTaskLog.created_at).all()
    
    def get_child_tasks_summary(self, parent_task_id: str) -> Dict:
        """
        Get a summary of child task statuses for a parent task.
        
        Args:
            parent_task_id: ID of the parent task
            
        Returns:
            Dict with counts by status: {"total": 10, "pending": 2, "started": 3, ...}
        """
        children = self.get_child_tasks(parent_task_id)
        
        summary = {
            "total": len(children),
            "pending": 0,
            "started": 0,
            "retry": 0,
            "success": 0,
            "failure": 0
        }
        
        for child in children:
            status = child.status
            if status in summary:
                summary[status] += 1
        
        return summary
