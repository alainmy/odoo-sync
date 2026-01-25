"""
Test de funcionalidad multi-instancia
Verifica que:
1. Cada usuario puede crear múltiples instancias
2. Solo una instancia puede estar activa por usuario
3. Los datos de sincronización están aislados por instancia
4. Las credenciales de cada instancia se usan correctamente
"""
import pytest
from sqlalchemy.orm import Session
from app.models.admin import Admin, WooCommerceInstance, ProductSync
from app.crud import crud_instance
from app.repositories import ProductSyncRepository
from datetime import datetime


def test_create_multiple_instances(db: Session):
    """Test: Usuario puede crear múltiples instancias"""
    # Crear usuario de prueba
    user = Admin(
        username="test_user",
        email="test@example.com",
        hashed_password="hashed123"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Crear primera instancia
    instance1 = crud_instance.create_instance(
        db=db,
        user_id=user.id,
        name="Tienda Principal",
        woocommerce_url="https://shop1.example.com",
        woocommerce_consumer_key="ck_111",
        woocommerce_consumer_secret="cs_111",
        odoo_url="https://odoo1.example.com",
        odoo_db="odoo_db1",
        odoo_username="admin1",
        odoo_password="pass1",
        is_active=True
    )
    
    # Crear segunda instancia
    instance2 = crud_instance.create_instance(
        db=db,
        user_id=user.id,
        name="Tienda Secundaria",
        woocommerce_url="https://shop2.example.com",
        woocommerce_consumer_key="ck_222",
        woocommerce_consumer_secret="cs_222",
        odoo_url="https://odoo2.example.com",
        odoo_db="odoo_db2",
        odoo_username="admin2",
        odoo_password="pass2",
        is_active=False
    )
    
    # Verificar que ambas instancias existen
    instances = crud_instance.get_instances_by_user(db, user_id=user.id)
    assert len(instances) == 2
    
    # Verificar que solo una está activa
    active_instances = [i for i in instances if i.is_active]
    assert len(active_instances) == 1
    assert active_instances[0].id == instance1.id


def test_activate_instance_deactivates_others(db: Session):
    """Test: Activar una instancia desactiva las demás del mismo usuario"""
    # Crear usuario y dos instancias
    user = Admin(username="test_user2", email="test2@example.com", hashed_password="hashed123")
    db.add(user)
    db.commit()
    db.refresh(user)
    
    instance1 = crud_instance.create_instance(
        db=db, user_id=user.id, name="Instancia 1",
        woocommerce_url="https://shop1.com", woocommerce_consumer_key="ck_1",
        woocommerce_consumer_secret="cs_1", odoo_url="https://odoo1.com",
        odoo_db="db1", odoo_username="user1", odoo_password="pass1", is_active=True
    )
    
    instance2 = crud_instance.create_instance(
        db=db, user_id=user.id, name="Instancia 2",
        woocommerce_url="https://shop2.com", woocommerce_consumer_key="ck_2",
        woocommerce_consumer_secret="cs_2", odoo_url="https://odoo2.com",
        odoo_db="db2", odoo_username="user2", odoo_password="pass2", is_active=False
    )
    
    # Verificar estado inicial
    db.refresh(instance1)
    db.refresh(instance2)
    assert instance1.is_active is True
    assert instance2.is_active is False
    
    # Activar la segunda instancia
    crud_instance.activate_instance(db, instance_id=instance2.id, user_id=user.id)
    
    # Verificar que la primera se desactivó
    db.refresh(instance1)
    db.refresh(instance2)
    assert instance1.is_active is False
    assert instance2.is_active is True


def test_sync_data_isolation(db: Session):
    """Test: Los datos de sincronización están aislados por instancia"""
    # Crear usuario y dos instancias
    user = Admin(username="test_user3", email="test3@example.com", hashed_password="hashed123")
    db.add(user)
    db.commit()
    db.refresh(user)
    
    instance1 = crud_instance.create_instance(
        db=db, user_id=user.id, name="Shop A",
        woocommerce_url="https://a.com", woocommerce_consumer_key="ck_a",
        woocommerce_consumer_secret="cs_a", odoo_url="https://odoo_a.com",
        odoo_db="db_a", odoo_username="admin_a", odoo_password="pass_a", is_active=True
    )
    
    instance2 = crud_instance.create_instance(
        db=db, user_id=user.id, name="Shop B",
        woocommerce_url="https://b.com", woocommerce_consumer_key="ck_b",
        woocommerce_consumer_secret="cs_b", odoo_url="https://odoo_b.com",
        odoo_db="db_b", odoo_username="admin_b", odoo_password="pass_b", is_active=False
    )
    
    # Crear registros de sincronización para cada instancia
    sync_repo = ProductSyncRepository(db)
    
    # Producto 1 sincronizado en instancia 1
    sync1 = sync_repo.create_product_sync(
        odoo_id=100,
        wc_id=200,
        instance_id=instance1.id,
        sku="SKU001",
        odoo_write_date=datetime.now(),
        published=True
    )
    
    # Producto 2 sincronizado en instancia 2 (mismo Odoo ID, diferente WC ID)
    sync2 = sync_repo.create_product_sync(
        odoo_id=100,  # Mismo producto en Odoo
        wc_id=300,    # Diferente ID en WooCommerce
        instance_id=instance2.id,
        sku="SKU001",
        odoo_write_date=datetime.now(),
        published=True
    )
    
    # Verificar que get_syncs filtra por instancia
    syncs_instance1 = sync_repo.get_syncs(instance_id=instance1.id)
    syncs_instance2 = sync_repo.get_syncs(instance_id=instance2.id)
    
    assert len(syncs_instance1) == 1
    assert len(syncs_instance2) == 1
    assert syncs_instance1[0].woocommerce_id == 200
    assert syncs_instance2[0].woocommerce_id == 300


def test_instance_credentials_different(db: Session):
    """Test: Cada instancia tiene credenciales independientes"""
    user = Admin(username="test_user4", email="test4@example.com", hashed_password="hashed123")
    db.add(user)
    db.commit()
    db.refresh(user)
    
    instance1 = crud_instance.create_instance(
        db=db, user_id=user.id, name="Credentials Test 1",
        woocommerce_url="https://wc1.com",
        woocommerce_consumer_key="unique_key_1",
        woocommerce_consumer_secret="unique_secret_1",
        odoo_url="https://odoo1.com",
        odoo_db="unique_db_1",
        odoo_username="unique_user_1",
        odoo_password="unique_pass_1",
        is_active=True
    )
    
    instance2 = crud_instance.create_instance(
        db=db, user_id=user.id, name="Credentials Test 2",
        woocommerce_url="https://wc2.com",
        woocommerce_consumer_key="unique_key_2",
        woocommerce_consumer_secret="unique_secret_2",
        odoo_url="https://odoo2.com",
        odoo_db="unique_db_2",
        odoo_username="unique_user_2",
        odoo_password="unique_pass_2",
        is_active=False
    )
    
    # Verificar que las credenciales son diferentes
    assert instance1.woocommerce_url != instance2.woocommerce_url
    assert instance1.woocommerce_consumer_key != instance2.woocommerce_consumer_key
    assert instance1.odoo_url != instance2.odoo_url
    assert instance1.odoo_db != instance2.odoo_db
    assert instance1.odoo_username != instance2.odoo_username
    
    # Verificar que se pueden recuperar correctamente
    retrieved1 = crud_instance.get_instance(db, instance_id=instance1.id, user_id=user.id)
    retrieved2 = crud_instance.get_instance(db, instance_id=instance2.id, user_id=user.id)
    
    assert retrieved1.woocommerce_consumer_key == "unique_key_1"
    assert retrieved2.woocommerce_consumer_key == "unique_key_2"


def test_get_active_instance(db: Session):
    """Test: get_active_instance devuelve la instancia activa correcta"""
    user = Admin(username="test_user5", email="test5@example.com", hashed_password="hashed123")
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Crear 3 instancias, solo la segunda activa
    instance1 = crud_instance.create_instance(
        db=db, user_id=user.id, name="Inactive 1",
        woocommerce_url="https://i1.com", woocommerce_consumer_key="ck1",
        woocommerce_consumer_secret="cs1", odoo_url="https://o1.com",
        odoo_db="db1", odoo_username="u1", odoo_password="p1", is_active=False
    )
    
    instance2 = crud_instance.create_instance(
        db=db, user_id=user.id, name="Active",
        woocommerce_url="https://active.com", woocommerce_consumer_key="ck_active",
        woocommerce_consumer_secret="cs_active", odoo_url="https://o_active.com",
        odoo_db="db_active", odoo_username="u_active", odoo_password="p_active", is_active=True
    )
    
    instance3 = crud_instance.create_instance(
        db=db, user_id=user.id, name="Inactive 2",
        woocommerce_url="https://i2.com", woocommerce_consumer_key="ck2",
        woocommerce_consumer_secret="cs2", odoo_url="https://o2.com",
        odoo_db="db2", odoo_username="u2", odoo_password="p2", is_active=False
    )
    
    # Verificar que get_active_instance devuelve la correcta
    active = crud_instance.get_active_instance(db, user_id=user.id)
    
    assert active is not None
    assert active.id == instance2.id
    assert active.name == "Active"
    assert active.woocommerce_consumer_key == "ck_active"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
