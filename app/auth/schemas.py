from pydantic import BaseModel, EmailStr, Field


class AuthCredentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class AccessTokenResponse(BaseModel):
    access_token: str


class UserResponse(BaseModel):
    id: str
    email: EmailStr
