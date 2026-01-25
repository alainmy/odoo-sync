"""
Repository para gestión de sincronización de atributos Odoo ↔ WooCommerce

IMPORTANTE: Este repository NO maneja CRUD de atributos (eso está en Odoo).
Solo maneja el MAPEO de sincronización entre Odoo y WooCommerce.
"""
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime

from app.models.attribute_models import AttributeSync, AttributeValueSync


class AttributeSyncRepository:
    """Repository para sincronización de atributos (solo mapeo, no CRUD)"""
    
    def __init__(self, db: Session):
        self.db = db
    
    # ==================== ATTRIBUTE SYNC ====================
    
    def create_attribute_sync(
        self,
        instance_id: int,
        odoo_attribute_id: int,
        odoo_name: Optional[str] = None,
        woocommerce_id: Optional[int] = None,
        slug: Optional[str] = None,
        created: bool = False,
        updated: bool = False,
        skipped: bool = False,
        error: bool = False,
        message: Optional[str] = None,
        error_details: Optional[str] = None
    ) -> AttributeSync:
        """Crear registro de sincronización de atributo"""
        sync = AttributeSync(
            instance_id=instance_id,
            odoo_attribute_id=odoo_attribute_id,
            odoo_name=odoo_name,
            woocommerce_id=woocommerce_id,
            slug=slug,
            created=created,
            updated=updated,
            skipped=skipped,
            error=error,
            message=message,
            error_details=error_details,
            sync_date=datetime.utcnow() if not error else None,
            last_exported_date=datetime.utcnow() if woocommerce_id else None
        )
        self.db.add(sync)
        self.db.commit()
        self.db.refresh(sync)
        return sync
    
    def get_attribute_sync_by_odoo_id(
        self,
        odoo_attribute_id: int,
        instance_id: int
    ) -> Optional[AttributeSync]:
        """Obtener sincronización por ID de Odoo"""
        return self.db.query(AttributeSync).filter(
            and_(
                AttributeSync.odoo_attribute_id == odoo_attribute_id,
                AttributeSync.instance_id == instance_id
            )
        ).first()
    
    def get_attribute_sync_by_woo_id(
        self,
        woocommerce_id: int,
        instance_id: int
    ) -> Optional[AttributeSync]:
        """Obtener sincronización por ID de WooCommerce"""
        return self.db.query(AttributeSync).filter(
            and_(
                AttributeSync.woocommerce_id == woocommerce_id,
                AttributeSync.instance_id == instance_id
            )
        ).first()
    
    def get_attribute_syncs(
        self,
        instance_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> List[AttributeSync]:
        """Obtener lista de sincronizaciones de atributos"""
        return self.db.query(AttributeSync).filter(
            AttributeSync.instance_id == instance_id
        ).offset(skip).limit(limit).all()
    
    def update_attribute_sync(
        self,
        sync_id: int,
        woocommerce_id: Optional[int] = None,
        slug: Optional[str] = None,
        created: Optional[bool] = None,
        updated: Optional[bool] = None,
        skipped: Optional[bool] = None,
        error: Optional[bool] = None,
        message: Optional[str] = None,
        error_details: Optional[str] = None
    ) -> Optional[AttributeSync]:
        """Actualizar registro de sincronización"""
        sync = self.db.query(AttributeSync).filter(
            AttributeSync.id == sync_id
        ).first()
        
        if not sync:
            return None
        
        if woocommerce_id is not None:
            sync.woocommerce_id = woocommerce_id
        if slug is not None:
            sync.slug = slug
        if created is not None:
            sync.created = created
        if updated is not None:
            sync.updated = updated
        if skipped is not None:
            sync.skipped = skipped
        if error is not None:
            sync.error = error
        if message is not None:
            sync.message = message
        if error_details is not None:
            sync.error_details = error_details
        
        sync.sync_date = datetime.utcnow()
        if woocommerce_id and not error:
            sync.last_exported_date = datetime.utcnow()
        
        self.db.commit()
        self.db.refresh(sync)
        return sync
    
    # ==================== ATTRIBUTE VALUE SYNC ====================
    
    def create_attribute_value_sync(
        self,
        instance_id: int,
        odoo_value_id: int,
        odoo_name: Optional[str] = None,
        woocommerce_id: Optional[int] = None,
        woocommerce_attribute_id: Optional[int] = None,
        slug: Optional[str] = None,
        created: bool = False,
        updated: bool = False,
        error: bool = False,
        message: Optional[str] = None
    ) -> AttributeValueSync:
        """Crear registro de sincronización de valor"""
        sync = AttributeValueSync(
            instance_id=instance_id,
            odoo_value_id=odoo_value_id,
            odoo_name=odoo_name,
            woocommerce_id=woocommerce_id,
            woocommerce_attribute_id=woocommerce_attribute_id,
            slug=slug,
            created=created,
            updated=updated,
            error=error,
            message=message,
            sync_date=datetime.utcnow() if not error else None,
            last_exported_date=datetime.utcnow() if woocommerce_id else None
        )
        self.db.add(sync)
        self.db.commit()
        self.db.refresh(sync)
        return sync
    
    def get_attribute_value_sync_by_odoo_id(
        self,
        odoo_value_id: int,
        instance_id: int
    ) -> Optional[AttributeValueSync]:
        """Obtener sincronización de valor por ID de Odoo"""
        return self.db.query(AttributeValueSync).filter(
            and_(
                AttributeValueSync.odoo_value_id == odoo_value_id,
                AttributeValueSync.instance_id == instance_id
            )
        ).first()
    
    def get_attribute_value_syncs_by_attribute(
        self,
        woocommerce_attribute_id: int,
        instance_id: int
    ) -> List[AttributeValueSync]:
        """Obtener todos los valores sincronizados de un atributo"""
        return self.db.query(AttributeValueSync).filter(
            and_(
                AttributeValueSync.woocommerce_attribute_id == woocommerce_attribute_id,
                AttributeValueSync.instance_id == instance_id
            )
        ).all()
    
    def update_attribute_value_sync(
        self,
        sync_id: int,
        woocommerce_id: Optional[int] = None,
        woocommerce_attribute_id: Optional[int] = None,
        slug: Optional[str] = None,
        created: Optional[bool] = None,
        updated: Optional[bool] = None,
        error: Optional[bool] = None,
        message: Optional[str] = None
    ) -> Optional[AttributeValueSync]:
        """Actualizar sincronización de valor"""
        sync = self.db.query(AttributeValueSync).filter(
            AttributeValueSync.id == sync_id
        ).first()
        
        if not sync:
            return None
        
        if woocommerce_id is not None:
            sync.woocommerce_id = woocommerce_id
        if woocommerce_attribute_id is not None:
            sync.woocommerce_attribute_id = woocommerce_attribute_id
        if slug is not None:
            sync.slug = slug
        if created is not None:
            sync.created = created
        if updated is not None:
            sync.updated = updated
        if error is not None:
            sync.error = error
        if message is not None:
            sync.message = message
        
        sync.sync_date = datetime.utcnow()
        if woocommerce_id and not error:
            sync.last_exported_date = datetime.utcnow()
        
        self.db.commit()
        self.db.refresh(sync)
        return sync
    
    # ==================== STATISTICS ====================
    
    def get_sync_statistics(self, instance_id: int) -> Dict:
        """Obtener estadísticas de sincronización"""
        total = self.db.query(AttributeSync).filter(
            AttributeSync.instance_id == instance_id
        ).count()
        
        synced = self.db.query(AttributeSync).filter(
            and_(
                AttributeSync.instance_id == instance_id,
                AttributeSync.woocommerce_id.isnot(None)
            )
        ).count()
        
        errors = self.db.query(AttributeSync).filter(
            and_(
                AttributeSync.instance_id == instance_id,
                AttributeSync.error == True
            )
        ).count()
        
        pending = total - synced
        
        return {
            "total_attributes": total,
            "synced": synced,
            "pending": pending,
            "errors": errors
        }
    
    def get_by_odoo_id(self, odoo_id: int, instance_id: int) -> Optional[AttributeSync]:
        """Alias for get_attribute_sync_by_odoo_id"""
        return self.get_attribute_sync_by_odoo_id(odoo_id, instance_id)
    
    def count_synced(self, instance_id: int) -> int:
        """Count synced attributes (with woocommerce_id)"""
        return self.db.query(AttributeSync).filter(
            and_(
                AttributeSync.instance_id == instance_id,
                AttributeSync.woocommerce_id.isnot(None),
                AttributeSync.error == False
            )
        ).count()
    
    def count_errors(self, instance_id: int) -> int:
        """Count attributes with errors"""
        return self.db.query(AttributeSync).filter(
            and_(
                AttributeSync.instance_id == instance_id,
                AttributeSync.error == True
            )
        ).count()

