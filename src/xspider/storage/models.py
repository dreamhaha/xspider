"""SQLAlchemy ORM models for xspider."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class User(Base):
    """Twitter user model."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(256))
    bio: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(256))
    url: Mapped[str | None] = mapped_column(String(512))
    followers_count: Mapped[int] = mapped_column(Integer, default=0)
    following_count: Mapped[int] = mapped_column(Integer, default=0)
    tweet_count: Mapped[int] = mapped_column(Integer, default=0)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    followings_scraped: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    ranking: Mapped["Ranking | None"] = relationship(back_populates="user", uselist=False)
    audit: Mapped["Audit | None"] = relationship(back_populates="user", uselist=False)

    __table_args__ = (
        Index("idx_users_followers", "followers_count", postgresql_ops={"followers_count": "DESC"}),
        Index("idx_users_depth", "depth"),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "bio": self.bio,
            "followers_count": self.followers_count,
            "following_count": self.following_count,
            "is_seed": self.is_seed,
            "depth": self.depth,
        }


class Edge(Base):
    """Follow relationship edge."""

    __tablename__ = "edges"

    source_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    target_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (Index("idx_edges_target", "target_id"),)


class Ranking(Base):
    """PageRank and influence ranking results."""

    __tablename__ = "rankings"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    pagerank_score: Mapped[float] = mapped_column(Float, default=0.0)
    in_degree: Mapped[int] = mapped_column(Integer, default=0)
    out_degree: Mapped[int] = mapped_column(Integer, default=0)
    hidden_score: Mapped[float] = mapped_column(Float, default=0.0)
    seed_followers_count: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship(back_populates="ranking")

    __table_args__ = (
        Index("idx_rankings_pagerank", "pagerank_score"),
        Index("idx_rankings_hidden", "hidden_score"),
    )


class Audit(Base):
    """AI content audit results."""

    __tablename__ = "audits"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    industry: Mapped[str] = mapped_column(String(128), nullable=False)
    is_relevant: Mapped[bool] = mapped_column(Boolean, default=False)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    topics: Mapped[str | None] = mapped_column(Text)  # JSON array
    tags: Mapped[str | None] = mapped_column(Text)  # JSON array
    reasoning: Mapped[str | None] = mapped_column(Text)
    model_used: Mapped[str | None] = mapped_column(String(64))
    tweets_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    audited_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship(back_populates="audit")

    __table_args__ = (Index("idx_audits_relevance", "relevance_score"),)
