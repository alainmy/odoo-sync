from re import I

import dotenv
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app import crud, schemas
from app.db.session import get_db
from app.auth.jwt import create_access_token
from app.auth.oauth2 import get_current_user
from app.core.security import get_password_hash, verify_password
from app.models.user_model import User
from app.schemas.user_schema import Token, UserBase, UserCreate
dotenv.load_dotenv()
router = APIRouter()


@router.post("/login", response_model=Token)
def login_for_access_token(db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()):
    user = crud.get_user_by_username(db, username=form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=400,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.username})
    return Token(access_token=access_token,
                 token_type="bearer",
                 is_superuser=user.is_superuser
                 )


@router.post("/token", response_model=Token)
def login_for_access_token(db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()):
    user = crud.get_user_by_username(db, username=form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=400,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.username})
    return Token(access_token=access_token, token_type="bearer")


@router.get("/users/me/", response_model=UserBase)
def read_users_me(current_user: schemas.user_schema.User = Depends(get_current_user)):
    return UserBase(username=current_user.username, email=current_user.email)


# List users
@router.get("/users", response_model=list[UserBase])
def read_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    users = crud.get_users(db, skip=skip, limit=limit)
    return [
        UserBase(id=user.id,
                 username=user.username,
                 email=user.email,
                 full_name=user.full_name,
                 is_active=user.is_active,
                 is_superuser=user.is_superuser)
        for user in users
    ]

# Create user
# TODO: Implement this endpoint


@router.post("/users/register", response_model=UserBase)
def create_users(
    data: UserCreate,
    db: Session = Depends(get_db),
):

    if crud.get_user_by_username(db, username=data.username):
        raise HTTPException(status_code=400, detail="Username already exists")

    # create password hash
    try:
        hashed_password = get_password_hash(data.password)
        user = User(username=data.username,
                    email=data.email,
                    hashed_password=hashed_password,
                    is_superuser=data.is_superuser)
        db.add(user)
        db.commit()
        db.refresh(user)
        return UserBase(username=user.username, email=user.email)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Update user


@router.put("/users/me", response_model=UserBase)
def update_users(
        user_id: int,
        data: UserBase,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user), ):
    user = crud.get_user_by_id(db, id=user_id)
    if not user:
        raise HTTPException(status_code=400, detail="User does not exist")

    try:
        if data.email:
            user.email = data.email
        if data.username:
            user.username = data.username
        if data.changed_password:
            user.hashed_password = get_password_hash(data.changed_password)
        if data.full_name:
            user.full_name = data.full_name
        if data.is_superuser:
            user.is_superuser = data.is_superuser
        db.commit()
        db.refresh(user)
        return UserBase(username=user.username, email=user.email)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Delete user
@router.delete("/users/{user_id}")
def delete_users(
        user_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user), ):
    user = crud.get_user_by_id(db, id=user_id)
    if not user:
        raise HTTPException(status_code=400, detail="User does not exist")

    db.delete(user)
    db.commit()
    return {"message": "User deleted"}
