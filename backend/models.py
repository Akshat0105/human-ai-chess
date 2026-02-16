"""Database models for User accounts and Game history."""

from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """Registered user account."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    games = db.relationship("Game", back_populates="user", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "createdAt": self.created_at.isoformat() + "Z",
        }


class Game(db.Model):
    """A completed chess game linked to a user."""

    __tablename__ = "games"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    started_at = db.Column(db.String(64))
    ended_at = db.Column(db.String(64))
    mode = db.Column(db.String(32))       # 'computer' | 'human-local'
    difficulty = db.Column(db.String(32))  # 'easy' | 'medium' | 'hard'
    result = db.Column(db.String(16))      # '1-0' | '0-1' | '1/2-1/2'
    moves = db.Column(db.Text)            # JSON string of moves array
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    user = db.relationship("User", back_populates="games")

    def to_summary(self):
        """Short summary for game list."""
        return {
            "id": self.id,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "mode": self.mode,
            "difficulty": self.difficulty,
            "result": self.result,
            "createdAt": self.created_at.isoformat() + "Z",
        }

    def to_detail(self):
        """Full detail including moves."""
        import json

        d = self.to_summary()
        try:
            d["moves"] = json.loads(self.moves) if self.moves else []
        except (json.JSONDecodeError, TypeError):
            d["moves"] = []
        return d
