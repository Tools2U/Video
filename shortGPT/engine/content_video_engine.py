import datetime
import os
import re
import shutil
import cv2

from shortGPT.api_utils.pexels_api import getBestVideo
from shortGPT.audio import audio_utils
from shortGPT.audio.audio_duration import get_asset_duration
from shortGPT.audio.voice_module import VoiceModule
from shortGPT.config.asset_db import AssetDatabase
from shortGPT.config.languages import Language
from shortGPT.editing_framework.editing_engine import (EditingEngine, EditingStep)
from shortGPT.editing_utils import captions
from shortGPT.engine.abstract_content_engine import AbstractContentEngine
from shortGPT.gpt import gpt_editing, gpt_translate, gpt_yt


class ContentVideoEngine(AbstractContentEngine):

    def __init__(self, voiceModule: VoiceModule, script: str, background_music_name="", id="",
                 watermark=None, isVerticalFormat=False, language: Language = Language.ENGLISH):
        super().__init__(id, "general_video", language, voiceModule)
        if not id:
            if watermark:
                self._db_watermark = watermark
            if background_music_name:
                self._db_background_music_name = background_music_name
            self._db_script = script
            self._db_format_vertical = isVerticalFormat

        self.stepDict = {
            1:  self._generateTempAudio,
            2:  self._speedUpAudio,
            3:  self._timeCaptions,
            4:  self._generateVideoSearchTerms,
            5:  self._generateVideoUrls,
            6:  self._chooseBackgroundMusic,
            7:  self._prepareBackgroundAssets,
            8: self._prepareCustomAssets,
            9: self._editAndRenderShort,
            10: self._addMetadata
        }

    def _generateTempAudio(self):
        if not self._db_script:
            raise NotImplementedError("generateScript method must set self._db_script.")
        if self._db_temp_audio_path:
            return
        self.verifyParameters(text=self._db_script)
        # Additional processing...

    def _timeCaptions(self):
        # Skip detailed caption timing
        self.verifyParameters(audioPath=self._db_audio_path)
        self._db_timed_captions = [[[0, 9999], ""]]  # Dummy value to satisfy later method checks

    def _generateVideoSearchTerms(self):
        # Preconfigured search term
        search_term = "nature landscape"  # Replace with your desired search term
        
        # Use this search term across the entire video duration
        self._db_timed_video_searches = [
            [[0, 9999], [search_term, search_term, search_term]]
        ]

    def _generateVideoUrls(self):
        timed_video_urls = []
        used_links = []
        current_time = 0  # Track the cumulative time to set proper start times

        for query in self._db_timed_video_searches[0][1]:  # Only use the predefined search terms
            url = getBestVideo(query, orientation_landscape=not self._db_format_vertical, used_vids=used_links)
            if url:
                video_start_time = current_time  # Start at the current cumulative time
                video_duration = self._getVideoDuration(url)  # Get the duration of the video
                video_end_time = video_start_time + video_duration  # Calculate the end time
                used_links.append(url.split('.hd')[0])
                timed_video_urls.append([[video_start_time, video_end_time], url])
                current_time = video_end_time  # Update current time to the end of this video

        self._db_timed_video_urls = timed_video_urls

    def _getVideoDuration(self, url):
        # Assuming the video is downloaded locally to analyze its duration
        cap = cv2.VideoCapture(url)
        if not cap.isOpened():
            raise IOError(f"Cannot open video file: {url}")
        duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        return duration

    def _chooseBackgroundMusic(self):
        if self._db_background_music_name:
            self._db_background_music_url = AssetDatabase.get_asset_link(self._db_background_music_name)

    def _prepareBackgroundAssets(self):
        self.verifyParameters(voiceover_audio_url=self._db_audio_path)
        if not self._db_voiceover_duration:
            self.logger("Rendering short: (1/4) preparing voice asset...")
            self._db_audio_path, self._db_voiceover_duration = get_asset_duration(
                self._db_audio_path, isVideo=False)

    def _prepareCustomAssets(self):
        self.logger("Rendering short: (3/4) preparing custom assets...")
        pass

    def _editAndRenderShort(self):
        self.verifyParameters(voiceover_audio_url=self._db_audio_path)
        # Additional rendering steps...

    def _addMetadata(self):
        # Metadata handling
        pass
