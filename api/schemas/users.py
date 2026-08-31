"""Pydantic 请求模型 — 自各路由文件集中, 逻辑零改动(批次2)。"""
import re

from pydantic import BaseModel, Field, field_validator, model_validator

USERNAME_RE = re.compile(r"^[a-z0-9_]{4,30}$")

class RegisterBody(BaseModel):
    username: str
    email: str
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip()
        if not USERNAME_RE.fullmatch(value):
            raise ValueError("用户名仅支持 4–30 位小写字母、数字或下划线")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("邮箱格式不正确")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise ValueError("密码至少包含一个字母和一个数字")
        return value

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("两次输入的密码不一致")
        return self



class LoginBody(BaseModel):
    account: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)



class ProfileBody(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    bio: str | None = Field(default=None, max_length=500)
    email: str = Field(min_length=3, max_length=200)
    location: str | None = Field(default=None, max_length=100)
    institution: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=500)
    orcid: str | None = Field(default=None, max_length=19)

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("bio")
    @classmethod
    def clean_bio(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("邮箱格式不正确")
        return value

    @field_validator("orcid")
    @classmethod
    def clean_orcid(cls, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = re.sub(r"[^\dXx]", "", value)
        if cleaned and not re.fullmatch(r"\d{15}[\dX]", cleaned):
            raise ValueError("ORCID 须为 16 位数字(末位可为X)")
        return cleaned if cleaned else None

    @field_validator("website")
    @classmethod
    def clean_website(cls, value: str | None) -> str | None:
        if not value:
            return None
        value = value.strip()
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("个人主页必须以 http:// 或 https:// 开头")
        return value or None



class TokenBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)



class PasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def valid_password(self):
        if self.new_password != self.confirm_password:
            raise ValueError("两次输入的新密码不一致")
        if not re.search(r"[A-Za-z]", self.new_password) or not re.search(r"\d", self.new_password):
            raise ValueError("新密码至少包含一个字母和一个数字")
        return self


