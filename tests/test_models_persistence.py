from blue_waves.models import AssetStatus, Language, MusicAsset, PodcastAsset, music_asset_from_dict, podcast_asset_from_dict


def test_music_manifest_survives_round_trip():
    asset = MusicAsset("m1", "bluewaves", "title", "ambient", "calm", 2, Language.EN)
    asset.media_manifest = {"enhancement": {"profile": "balanced_audio"}}
    restored = music_asset_from_dict(asset.to_dict())
    assert restored.media_manifest == asset.media_manifest


def test_podcast_manifest_survives_round_trip():
    asset = PodcastAsset("p1", "bluewaves", "title", "topic", "voice", Language.EN, 2)
    asset.media_manifest = {"enhancement": {"profile": "balanced_audio"}}
    restored = podcast_asset_from_dict(asset.to_dict())
    assert restored.media_manifest == asset.media_manifest
