"""Tables of the titles module (all prefixed ``titles_``; never referenced by another module).

``play_ref`` columns are *soft* references (``<namespace>:<id>``) to content owned by
other modules. They are never cleared automatically: a source that disappears (e.g. a
playlist sync drops it for a day) makes the title *unavailable* at read time and
heals by itself when it returns — curated links are not lost.

Texts: the base columns (``name``, ``synopsis``) hold the default-locale original; the
``*_texts`` tables hold translations, one row per (owner, locale). Reads fall back to the
original for a language that has no translation.
"""

from __future__ import annotations

from sqlalchemy.orm import Mapped, relationship

from app.kernel.db import created_at_column, db, updated_at_column

title_genres = db.Table(
    "titles_title_genres",
    db.Column("title_id", db.Integer, db.ForeignKey("titles_titles.id", ondelete="CASCADE"), primary_key=True),
    db.Column("genre_id", db.Integer, db.ForeignKey("titles_genres.id", ondelete="CASCADE"), primary_key=True),
)


class GenreText(db.Model):
    __tablename__ = "titles_genre_texts"

    genre_id = db.Column(db.Integer, db.ForeignKey("titles_genres.id", ondelete="CASCADE"), primary_key=True)
    locale = db.Column(db.String(8), primary_key=True)
    name = db.Column(db.String(80), nullable=False)


class Genre(db.Model):
    __tablename__ = "titles_genres"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), nullable=False, unique=True)
    name = db.Column(db.String(80), nullable=False)

    texts: Mapped[list[GenreText]] = relationship(GenreText, cascade="all, delete-orphan", lazy="selectin")


class TitleText(db.Model):
    __tablename__ = "titles_title_texts"

    title_id = db.Column(db.Integer, db.ForeignKey("titles_titles.id", ondelete="CASCADE"), primary_key=True)
    locale = db.Column(db.String(8), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    synopsis = db.Column(db.Text)


class EpisodeText(db.Model):
    __tablename__ = "titles_episode_texts"

    episode_id = db.Column(db.Integer, db.ForeignKey("titles_episodes.id", ondelete="CASCADE"), primary_key=True)
    locale = db.Column(db.String(8), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    synopsis = db.Column(db.Text)


class Title(db.Model):
    __tablename__ = "titles_titles"
    __table_args__ = (
        db.CheckConstraint("kind IN ('movie','series')", name="kind_valid"),
        db.CheckConstraint("rating IN ('general','teen','adult','unrated')", name="rating_valid"),
        db.CheckConstraint("kind = 'movie' OR play_ref IS NULL", name="series_no_play_ref"),
        db.Index("ix_titles_titles_published_featured", "is_published", "featured_rank"),
    )

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), nullable=False, unique=True)
    kind = db.Column(db.String(10), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    synopsis = db.Column(db.Text)
    year = db.Column(db.Integer, index=True)
    runtime_minutes = db.Column(db.Integer)
    rating = db.Column(db.String(10), nullable=False, default="unrated")
    poster_url = db.Column(db.String(1024))
    backdrop_url = db.Column(db.String(1024))
    play_ref = db.Column(db.String(64), index=True)
    featured_rank = db.Column(db.Integer)
    is_published = db.Column(db.Boolean, nullable=False, default=True)
    created_at = created_at_column()
    updated_at = updated_at_column()

    texts: Mapped[list[TitleText]] = relationship(TitleText, cascade="all, delete-orphan", lazy="selectin")
    genres: Mapped[list[Genre]] = relationship(Genre, secondary=title_genres, lazy="selectin", order_by=Genre.name)
    seasons: Mapped[list[Season]] = relationship(
        "Season", back_populates="title", cascade="all, delete-orphan", order_by="Season.number", lazy="selectin"
    )


class Season(db.Model):
    __tablename__ = "titles_seasons"
    __table_args__ = (db.UniqueConstraint("title_id", "number", name="uq_titles_seasons_title_id_number"),)

    id = db.Column(db.Integer, primary_key=True)
    title_id = db.Column(db.Integer, db.ForeignKey("titles_titles.id", ondelete="CASCADE"), nullable=False)
    number = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(200))

    title: Mapped[Title] = relationship(Title, back_populates="seasons")
    episodes: Mapped[list[Episode]] = relationship(
        "Episode", back_populates="season", cascade="all, delete-orphan", order_by="Episode.number", lazy="selectin"
    )


class Episode(db.Model):
    __tablename__ = "titles_episodes"
    __table_args__ = (db.UniqueConstraint("season_id", "number", name="uq_titles_episodes_season_id_number"),)

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey("titles_seasons.id", ondelete="CASCADE"), nullable=False)
    number = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    synopsis = db.Column(db.Text)
    runtime_minutes = db.Column(db.Integer)
    still_url = db.Column(db.String(1024))
    play_ref = db.Column(db.String(64), index=True)  # NULL ⇔ announced, not playable yet

    season: Mapped[Season] = relationship(Season, back_populates="episodes")
    texts: Mapped[list[EpisodeText]] = relationship(EpisodeText, cascade="all, delete-orphan", lazy="selectin")
