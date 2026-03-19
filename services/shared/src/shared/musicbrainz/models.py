"""Pydantic models for MusicBrainz API responses."""

from pydantic import BaseModel, Field


class MBArtistCredit(BaseModel):
    """Artist credit from a MusicBrainz recording."""

    name: str
    mbid: str = Field(alias="id", default="")

    model_config = {"populate_by_name": True}


class MBRelease(BaseModel):
    """A release (album) from MusicBrainz."""

    mbid: str = Field(alias="id", default="")
    title: str = ""
    date: str = ""
    country: str = ""
    status: str = ""
    barcode: str = ""
    label: str = ""
    catalog_number: str = ""

    model_config = {"populate_by_name": True}


class MBGenre(BaseModel):
    """Genre tag from MusicBrainz."""

    name: str = ""
    count: int = 0


class MBRecording(BaseModel):
    """A recording (track) from MusicBrainz."""

    mbid: str = Field(alias="id", default="")
    title: str = ""
    length: int | None = None
    artist_credits: list[MBArtistCredit] = Field(alias="artist-credit", default_factory=list)
    releases: list[MBRelease] = Field(default_factory=list)
    genres: list[MBGenre] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @property
    def first_release(self) -> MBRelease | None:
        """Return the earliest release by date, if any."""
        dated = [r for r in self.releases if r.date]
        if not dated:
            return self.releases[0] if self.releases else None
        return min(dated, key=lambda r: r.date)


class MBArtist(BaseModel):
    """An artist from MusicBrainz."""

    mbid: str = Field(alias="id", default="")
    name: str = ""
    sort_name: str = Field(alias="sort-name", default="")
    disambiguation: str = ""
    area: str = ""
    begin_date: str = ""
    genres: list[MBGenre] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class MBRecordingSearchResult(BaseModel):
    """Wrapper for recording search results."""

    recordings: list[MBRecording] = Field(default_factory=list)
    count: int = 0
