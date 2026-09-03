from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


class YouTubeUploadService:
    """YouTube Data API v3 upload service with OAuth 2.0."""

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/yt-analytics.readonly"]

    # Category IDs: 27=Education, 28=Science & Technology, 24=Entertainment
    DEFAULT_CATEGORY = "27"

    def __init__(self, credentials_path: Path, client_id: str, client_secret: str):
        self.credentials_path = credentials_path
        self.client_id = client_id
        self.client_secret = client_secret
        self._credentials: Optional[Credentials] = None
        self._service = None

    def _load_credentials(self) -> Credentials:
        """Load and refresh OAuth credentials."""
        if self._credentials and self._credentials.valid:
            return self._credentials

        if self.credentials_path.exists():
            self._credentials = Credentials.from_authorized_user_file(
                str(self.credentials_path), self.SCOPES
            )

        if self._credentials and self._credentials.expired and self._credentials.refresh_token:
            self._credentials.refresh(Request())
            self._save_credentials()
        elif not self._credentials or not self._credentials.valid:
            raise RuntimeError("YouTube credentials not found or invalid. Run OAuth flow first.")

        return self._credentials

    def _save_credentials(self) -> None:
        """Save credentials to file."""
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
        self.credentials_path.write_text(self._credentials.to_json())

    def _get_service(self):
        """Get or create YouTube service."""
        if self._service is None:
            creds = self._load_credentials()
            self._service = build("youtube", "v3", credentials=creds)
        return self._service

    @staticmethod
    def generate_seo_metadata(
        content_type: str,
        topic: str,
        pillar: str = "education",
        language: str = "en",
        extra_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate SEO-optimized metadata for YouTube upload."""
        
        # Title templates by content type
        title_templates = {
            "video": "{topic} - Complete Tutorial",
            "music": "{topic} - {mood} {genre} Background Music",
            "podcast": "{topic} - Podcast Episode",
        }
        
        # Base tags by content type
        base_tags = {
            "video": ["tutorial", "education", "how to", "learn"],
            "music": ["background music", "royalty free", "no copyright"],
            "podcast": ["podcast", "education", "audio"],
        }
        
        # Pillar-specific tags
        pillar_tags = {
            "education": ["educational", "learning", "study", "course"],
            "tech": ["technology", "programming", "coding", "software"],
            "science": ["science", "research", "discovery", "experiment"],
            "business": ["business", "entrepreneurship", "startup", "marketing"],
        }
        
        # Language-specific tags
        lang_tags = {
            "en": ["english"],
            "ar": ["arabic", "العربية"],
            "es": ["spanish", "español"],
            "fr": ["french", "français"],
        }
        
        title = title_templates.get(content_type, "{topic}").format(topic=topic)
        title = title[:95]  # Leave room for branding
        
        # Build description
        desc_lines = [
            f"Learn about {topic} in this {content_type}.",
            "",
            "🔔 Subscribe for more educational content!",
            "👍 Like and comment if this helped you.",
            "",
            "#Education #Tutorial #Learning",
        ]
        
        if pillar != "education":
            desc_lines.insert(2, f"Category: {pillar.title()}")
        
        description = "\n".join(desc_lines)
        
        # Combine tags
        tags = set(base_tags.get(content_type, []))
        tags.update(pillar_tags.get(pillar, []))
        tags.update(lang_tags.get(language, []))
        if extra_tags:
            tags.update(extra_tags)
        
        # Limit to 500 chars total for tags
        tag_list = list(tags)[:15]
        
        return {
            "title": title,
            "description": description[:4800],
            "tags": tag_list,
            "category_id": "27",  # Education
        }

    def upload_video(
        self,
        video_path: Path,
        title: str,
        description: str = "",
        tags: list[str] | None = None,
        category_id: str = "27",  # Education
        privacy_status: str = "private",  # private, unlisted, public
    ) -> dict[str, Any]:
        """Upload a video to YouTube."""
        service = self._get_service()

        body = {
            "snippet": {
                "title": title[:100],  # YouTube max 100 chars
                "description": description[:5000],  # YouTube max 5000 chars
                "tags": tags or [],
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/*")

        request = service.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"Upload progress: {int(status.progress() * 100)}%")

        video_id = response.get("id")
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        return {
            "video_id": video_id,
            "video_url": video_url,
            "title": title,
            "privacy_status": privacy_status,
        }

    def upload_audio_as_video(
        self,
        audio_path: Path,
        title: str,
        description: str = "",
        tags: list[str] | None = None,
        privacy_status: str = "private",
        thumbnail_path: Path | None = None,
    ) -> dict[str, Any]:
        """Upload audio file as a video (with static image) to YouTube."""
        return self.upload_video(audio_path, title, description, tags, privacy_status=privacy_status)

    def set_thumbnail(self, video_id: str, thumbnail_path: Path) -> bool:
        """Set custom thumbnail for video."""
        try:
            service = self._get_service()
            media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")
            service.thumbnails().set(videoId=video_id, media_body=media).execute()
            return True
        except Exception as e:
            print(f"Failed to set thumbnail: {e}")
            return False

    def get_video_analytics(self, video_id: str) -> dict[str, Any]:
        """Get basic video analytics."""
        try:
            service = self._get_service()
            response = service.videos().list(part="statistics", id=video_id).execute()
            items = response.get("items", [])
            if items:
                stats = items[0].get("statistics", {})
                return {
                    "view_count": int(stats.get("viewCount", 0)),
                    "like_count": int(stats.get("likeCount", 0)),
                    "comment_count": int(stats.get("commentCount", 0)),
                }
        except Exception as e:
            print(f"Failed to get analytics: {e}")
        return {"view_count": 0, "like_count": 0, "comment_count": 0}


def create_youtube_service_from_oauth(
    oauth_credentials: dict[str, Any],
    credentials_dir: Path,
) -> YouTubeUploadService:
    """Create YouTubeUploadService from OAuth credentials stored in connection store."""
    creds_path = credentials_dir / "youtube_token.json"
    creds_path.write_text(json.dumps(oauth_credentials))

    client_id = oauth_credentials.get("client_id", "")
    client_secret = oauth_credentials.get("client_secret", "")

    return YouTubeUploadService(creds_path, client_id, client_secret)