"""Track, artist, and album detail with Spotify + MusicBrainz enrichment."""

import logging

import httpx
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.exceptions import TokenNotFoundError, TokenRefreshError
from app.dependencies import cache_backend
from app.explorer.schemas import (
    AlbumDetail,
    AlbumTrackItem,
    ArtistDetail,
    AudioFeaturesData,
    MusicBrainzAlbumEnrichment,
    MusicBrainzArtistEnrichment,
    MusicBrainzExternalUrls,
    MusicBrainzTrackEnrichment,
    RecentPlayItem,
    SpotifyAlbumEnrichment,
    SpotifyArtistEnrichment,
    SpotifyImage,
    SpotifyTrackEnrichment,
    TrackArtistRef,
    TrackDetail,
    TrackDetailArtist,
)
from app.explorer.services._base import BaseExplorerService
from shared.db.models.music import Artist, Play, Track, TrackArtist
from shared.spotify.exceptions import SpotifyClientError

logger = logging.getLogger(__name__)


class DetailService(BaseExplorerService):
    """Provides entity detail pages with enrichment from Spotify and MusicBrainz."""

    async def get_track_detail(
        self, user_id: int, track_id: int, session: AsyncSession, *, request: object | None = None
    ) -> TrackDetail | None:
        """Return detailed track info with play stats, audio features, and recent plays."""
        stats_result = await session.execute(
            select(
                func.count(),
                func.min(Play.played_at),
                func.max(Play.played_at),
                func.coalesce(func.sum(Play.ms_played), 0),
            ).where(Play.user_id == user_id, Play.track_id == track_id)
        )
        play_count, first_played, last_played, total_ms = stats_result.one()

        if play_count == 0:
            return None

        result = await session.execute(
            select(Track)
            .where(Track.id == track_id)
            .options(selectinload(Track.artists), selectinload(Track.audio_features))
        )
        track = result.scalar_one_or_none()
        if track is None:
            return None

        recent_result = await session.execute(
            select(Play.played_at, Play.ms_played, Play.context_type)
            .where(Play.user_id == user_id, Play.track_id == track_id)
            .order_by(desc(Play.played_at))
            .limit(20)
        )
        recent_plays = [
            RecentPlayItem(played_at=row.played_at, ms_played=row.ms_played, context_type=row.context_type)
            for row in recent_result.all()
        ]

        audio_features: AudioFeaturesData | None = None
        if track.audio_features is not None:
            af = track.audio_features
            audio_features = AudioFeaturesData(
                danceability=af.danceability,
                energy=af.energy,
                valence=af.valence,
                acousticness=af.acousticness,
                instrumentalness=af.instrumentalness,
                speechiness=af.speechiness,
                tempo=af.tempo,
                loudness=af.loudness,
                key=af.key,
                mode=af.mode,
                time_signature=af.time_signature,
                liveness=af.liveness,
            )

        artists = [TrackArtistRef(artist_id=a.id, name=a.name) for a in track.artists]

        spotify_enrichment: SpotifyTrackEnrichment | None = None
        if track.spotify_track_id:
            spotify_enrichment = await self._enrich_track_spotify(track.spotify_track_id, user_id, session)

        isrc = spotify_enrichment.isrc if spotify_enrichment else None
        artist_name = artists[0].name if artists else ""
        mb_enrichment = await self._enrich_track_musicbrainz(isrc, artist_name, track.name, request=request)

        return TrackDetail(
            track_id=track.id,
            name=track.name,
            spotify_track_id=track.spotify_track_id,
            duration_ms=track.duration_ms,
            album_name=track.album_name,
            album_spotify_id=track.album_spotify_id,
            artists=artists,
            play_count=play_count,
            first_played=first_played,
            last_played=last_played,
            total_ms_played=total_ms,
            audio_features=audio_features,
            recent_plays=recent_plays,
            spotify=spotify_enrichment,
            musicbrainz=mb_enrichment,
        )

    async def get_artist_detail(
        self, user_id: int, artist_id: int, session: AsyncSession, *, request: object | None = None
    ) -> ArtistDetail | None:
        """Return detailed artist info with play stats and top tracks."""
        stats_result = await session.execute(
            select(
                func.count(),
                func.count(func.distinct(Play.track_id)),
                func.coalesce(func.sum(Play.ms_played), 0),
                func.min(Play.played_at),
                func.max(Play.played_at),
            )
            .select_from(Play)
            .join(TrackArtist, TrackArtist.track_id == Play.track_id)
            .where(Play.user_id == user_id, TrackArtist.artist_id == artist_id)
        )
        play_count, unique_tracks, total_ms, first_played, last_played = stats_result.one()

        if play_count == 0:
            return None

        result = await session.execute(select(Artist).where(Artist.id == artist_id))
        artist = result.scalar_one_or_none()
        if artist is None:
            return None

        top_tracks_result = await session.execute(
            select(
                Track.id.label("track_id"),
                Track.name.label("name"),
                func.count().label("play_count"),
            )
            .select_from(Play)
            .join(Track, Track.id == Play.track_id)
            .join(TrackArtist, TrackArtist.track_id == Play.track_id)
            .where(Play.user_id == user_id, TrackArtist.artist_id == artist_id)
            .group_by(Track.id, Track.name)
            .order_by(desc(func.count()))
            .limit(20)
        )
        top_tracks = [
            TrackDetailArtist(track_id=row.track_id, name=row.name, play_count=row.play_count)
            for row in top_tracks_result.all()
        ]

        spotify_enrichment: SpotifyArtistEnrichment | None = None
        if artist.spotify_artist_id:
            spotify_enrichment = await self._enrich_artist_spotify(artist.spotify_artist_id, user_id, session)

        mb_enrichment = await self._enrich_artist_musicbrainz(artist.name, request=request)

        return ArtistDetail(
            artist_id=artist.id,
            name=artist.name,
            spotify_artist_id=artist.spotify_artist_id,
            play_count=play_count,
            unique_tracks=unique_tracks,
            total_ms_played=total_ms,
            first_played=first_played,
            last_played=last_played,
            top_tracks=top_tracks,
            spotify=spotify_enrichment,
            musicbrainz=mb_enrichment,
        )

    async def get_album_detail(
        self, user_id: int, album_spotify_id: str, session: AsyncSession, *, request: object | None = None
    ) -> AlbumDetail | None:
        """Return album detail with per-track play stats."""
        user_track_ids_result = await session.execute(
            select(func.distinct(Play.track_id))
            .join(Track, Track.id == Play.track_id)
            .where(Play.user_id == user_id, Track.album_spotify_id == album_spotify_id)
        )
        user_played_track_ids = set(user_track_ids_result.scalars().all())
        if not user_played_track_ids:
            return None

        tracks_result = await session.execute(
            select(Track)
            .where(Track.album_spotify_id == album_spotify_id, Track.id.in_(user_played_track_ids))
            .options(selectinload(Track.artists))
        )
        tracks = list(tracks_result.scalars().all())
        if not tracks:
            return None

        album_name = tracks[0].album_name or ""
        artist_name_set: set[str] = set()
        for t in tracks:
            for a in t.artists:
                artist_name_set.add(a.name)

        track_ids = [t.id for t in tracks]

        play_counts_result = await session.execute(
            select(Play.track_id, func.count().label("play_count"))
            .where(Play.user_id == user_id, Play.track_id.in_(track_ids))
            .group_by(Play.track_id)
        )
        play_counts: dict[int, int] = {row.track_id: row.play_count for row in play_counts_result.all()}

        album_tracks = [
            AlbumTrackItem(
                track_id=t.id,
                name=t.name,
                play_count=play_counts.get(t.id, 0),
                duration_ms=t.duration_ms,
            )
            for t in tracks
        ]

        total_play_count = sum(item.play_count for item in album_tracks)
        unique_track_count = sum(1 for item in album_tracks if item.play_count > 0)

        spotify_enrichment = await self._enrich_album_spotify(album_spotify_id, user_id, session)

        first_artist = sorted(artist_name_set)[0] if artist_name_set else ""
        mb_enrichment = await self._enrich_album_musicbrainz(album_name, first_artist, request=request)

        return AlbumDetail(
            album_spotify_id=album_spotify_id,
            name=album_name,
            artist_names=sorted(artist_name_set),
            play_count=total_play_count,
            unique_tracks=unique_track_count,
            tracks=album_tracks,
            spotify=spotify_enrichment,
            musicbrainz=mb_enrichment,
        )

    # ── Spotify enrichment helpers ─────────────────────────────

    async def _enrich_track_spotify(
        self, spotify_track_id: str, user_id: int, session: AsyncSession
    ) -> SpotifyTrackEnrichment | None:
        """Fetch track enrichment from Spotify API with caching."""
        cache_key = f"sp:track:{spotify_track_id}"
        cached = await cache_backend.get(cache_key)
        if cached is not None:
            return SpotifyTrackEnrichment.model_validate(cached)
        try:
            client = await self._get_spotify_client(user_id, session)
            sp_track = await client.get_track(spotify_track_id)
            images = []
            if sp_track.album and sp_track.album.images:
                images = [
                    SpotifyImage(url=img.url, height=img.height, width=img.width) for img in sp_track.album.images
                ]
            result = SpotifyTrackEnrichment(
                images=images,
                popularity=sp_track.popularity,
                isrc=sp_track.external_ids.isrc if sp_track.external_ids else None,
                preview_url=sp_track.preview_url,
                external_url=sp_track.external_urls.get("spotify") if sp_track.external_urls else None,
            )
            ttl: int = await self.settings.get("explorer.enrichment_cache_ttl_seconds", 86400, session)
            await cache_backend.set(cache_key, result.model_dump(), ttl)
            return result
        except (TokenNotFoundError, TokenRefreshError, SpotifyClientError, httpx.HTTPError) as exc:
            logger.debug("Spotify enrichment failed for track %s: %s", spotify_track_id, exc)
            return None

    async def _enrich_artist_spotify(
        self, spotify_artist_id: str, user_id: int, session: AsyncSession
    ) -> SpotifyArtistEnrichment | None:
        """Fetch artist enrichment from Spotify API with caching."""
        cache_key = f"sp:artist:{spotify_artist_id}"
        cached = await cache_backend.get(cache_key)
        if cached is not None:
            return SpotifyArtistEnrichment.model_validate(cached)
        try:
            client = await self._get_spotify_client(user_id, session)
            sp_artist = await client.get_artist(spotify_artist_id)
            images = []
            if sp_artist.images:
                images = [SpotifyImage(url=img.url, height=img.height, width=img.width) for img in sp_artist.images]
            followers_total = None
            if sp_artist.followers and isinstance(sp_artist.followers, dict):
                followers_total = sp_artist.followers.get("total")
            result = SpotifyArtistEnrichment(
                images=images,
                genres=sp_artist.genres,
                popularity=sp_artist.popularity,
                followers=followers_total,
                external_url=sp_artist.external_urls.get("spotify") if sp_artist.external_urls else None,
            )
            ttl: int = await self.settings.get("explorer.enrichment_cache_ttl_seconds", 86400, session)
            await cache_backend.set(cache_key, result.model_dump(), ttl)
            return result
        except (TokenNotFoundError, TokenRefreshError, SpotifyClientError, httpx.HTTPError) as exc:
            logger.debug("Spotify enrichment failed for artist %s: %s", spotify_artist_id, exc)
            return None

    async def _enrich_album_spotify(
        self, album_spotify_id: str, user_id: int, session: AsyncSession
    ) -> SpotifyAlbumEnrichment | None:
        """Fetch album enrichment from Spotify API with caching."""
        cache_key = f"sp:album:{album_spotify_id}"
        cached = await cache_backend.get(cache_key)
        if cached is not None:
            return SpotifyAlbumEnrichment.model_validate(cached)
        try:
            client = await self._get_spotify_client(user_id, session)
            sp_album = await client.get_album(album_spotify_id)
            images = []
            if sp_album.images:
                images = [SpotifyImage(url=img.url, height=img.height, width=img.width) for img in sp_album.images]
            result = SpotifyAlbumEnrichment(
                images=images,
                release_date=sp_album.release_date,
                label=sp_album.label,
                total_tracks=sp_album.total_tracks,
                external_url=sp_album.external_urls.get("spotify") if sp_album.external_urls else None,
            )
            ttl: int = await self.settings.get("explorer.enrichment_cache_ttl_seconds", 86400, session)
            await cache_backend.set(cache_key, result.model_dump(), ttl)
            return result
        except (TokenNotFoundError, TokenRefreshError, SpotifyClientError, httpx.HTTPError) as exc:
            logger.debug("Spotify enrichment failed for album %s: %s", album_spotify_id, exc)
            return None

    # ── MusicBrainz enrichment helpers ────────────────────────────

    async def _enrich_track_musicbrainz(
        self, isrc: str | None, artist_name: str, track_name: str, request: object | None = None
    ) -> MusicBrainzTrackEnrichment | None:
        """Fetch track metadata from MusicBrainz (ISRC lookup with fallback)."""
        mb_client = self._get_mb_client(request)
        if mb_client is None:
            return None
        try:
            recording = None
            if isrc:
                recording = await mb_client.lookup_recording_by_isrc(isrc)
            if recording is None and artist_name and track_name:
                recording = await mb_client.search_recording(artist_name, track_name)
            if recording is None:
                return None

            release = recording.first_release
            genres = [g.name for g in recording.genres if g.name]

            return MusicBrainzTrackEnrichment(
                mbid=recording.mbid,
                label=release.label if release else None,
                release_date=release.date if release else None,
                country=release.country if release else None,
                genres=genres,
                external_urls=MusicBrainzExternalUrls(
                    musicbrainz=f"https://musicbrainz.org/recording/{recording.mbid}" if recording.mbid else None,
                ),
            )
        except Exception as exc:
            logger.debug("MusicBrainz enrichment failed: %s", exc)
            return None

    async def _enrich_artist_musicbrainz(
        self, artist_name: str, request: object | None = None
    ) -> MusicBrainzArtistEnrichment | None:
        """Fetch artist metadata from MusicBrainz via direct artist search."""
        mb_client = self._get_mb_client(request)
        if mb_client is None:
            return None
        try:
            artist = await mb_client.search_artist(artist_name)
            if artist is None:
                return None
            genres = [g.name for g in artist.genres if g.name]
            return MusicBrainzArtistEnrichment(
                mbid=artist.mbid,
                area=artist.area or None,
                disambiguation=artist.disambiguation or None,
                begin_date=artist.begin_date or None,
                genres=genres,
                external_urls=MusicBrainzExternalUrls(
                    musicbrainz=f"https://musicbrainz.org/artist/{artist.mbid}" if artist.mbid else None,
                ),
            )
        except Exception as exc:
            logger.debug("MusicBrainz artist enrichment failed: %s", exc)
            return None

    async def _enrich_album_musicbrainz(
        self, album_name: str, artist_name: str, request: object | None = None
    ) -> MusicBrainzAlbumEnrichment | None:
        """Fetch album metadata from MusicBrainz via recording search.

        Note: MusicBrainzClient has no dedicated release search, so we use
        search_recording(artist, album_name) as a best-effort heuristic to
        find a recording from the album, then extract its first release.
        """
        mb_client = self._get_mb_client(request)
        if mb_client is None:
            return None
        try:
            recording = await mb_client.search_recording(artist_name, album_name)
            if recording is None:
                return None
            release = recording.first_release
            if release is None or not release.mbid:
                return None
            detailed = await mb_client.get_release(release.mbid)
            if detailed is None:
                return None
            return MusicBrainzAlbumEnrichment(
                mbid=detailed.mbid,
                label=detailed.label or None,
                catalog_number=detailed.catalog_number or None,
                country=detailed.country or None,
                barcode=detailed.barcode or None,
                external_urls=MusicBrainzExternalUrls(
                    musicbrainz=f"https://musicbrainz.org/release/{detailed.mbid}" if detailed.mbid else None,
                ),
            )
        except Exception as exc:
            logger.debug("MusicBrainz album enrichment failed: %s", exc)
            return None
