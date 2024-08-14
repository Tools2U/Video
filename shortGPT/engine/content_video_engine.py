import datetime
import os
import re
import shutil
import logging
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
from shortGPT.gpt import gpt_translate, gpt_yt

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
            1: self._generateTempAudio,
            2: self._speedUpAudio,
            3: self._timeCaptions,
            4: self._generateVideoSearchTerms,
            5: self._generateVideoUrls,
            6: self._chooseBackgroundMusic,
            7: self._prepareBackgroundAssets,
            8: self._prepareCustomAssets,
            9: self._editAndRenderShort,
            10: self._addMetadata
        }

    def _generateTempAudio(self):
        logging.info("Starting _generateTempAudio step...")
        if not self._db_script:
            raise NotImplementedError("generateScript method must set self._db_script.")
        if self._db_temp_audio_path:
            return
        self.verifyParameters(text=self._db_script)
        script = self._db_script
        if self._db_language != Language.ENGLISH.value:
            logging.info("Translating script...")
            self._db_translated_script = gpt_translate.translateContent(script, self._db_language)
            script = self._db_translated_script
        self._db_temp_audio_path = self.voiceModule.generate_voice(
            script, self.dynamicAssetDir + "temp_audio_path.wav")
        logging.info(f"Generated temporary audio at {self._db_temp_audio_path}")

    def _speedUpAudio(self):
        logging.info("Starting _speedUpAudio step...")
        if self._db_audio_path:
            return
        self.verifyParameters(tempAudioPath=self._db_temp_audio_path)
        self._db_audio_path = self._db_temp_audio_path
        logging.info(f"Audio path set to {self._db_audio_path}")

    def _timeCaptions(self):
        logging.info("Starting _timeCaptions step...")
        self.verifyParameters(audioPath=self._db_audio_path)
        whisper_analysis = audio_utils.audioToText(self._db_audio_path)
        max_len = 15
        if not self._db_format_vertical:
            max_len = 30
        self._db_timed_captions = captions.getCaptionsWithTime(
            whisper_analysis, maxCaptionSize=max_len)
        logging.info(f"Timed captions generated: {self._db_timed_captions}")

    def _generateVideoSearchTerms(self):
        logging.info("Starting _generateVideoSearchTerms step...")
        self.verifyParameters(captionsTimed=self._db_timed_captions)
        self._db_timed_video_searches = [
            [[0, 9999], ["nature landscape", "nature landscape", "nature landscape"]]
        ]
        logging.info(f"Video search terms generated: {self._db_timed_video_searches}")

    def _generateVideoUrls(self):
        logging.info("Starting _generateVideoUrls step...")
        try:
            timed_video_urls = []
            used_links = []
            current_time = 0  # Track the cumulative time to set proper start times

            for query in self._db_timed_video_searches[0][1]:  # Only use the predefined search terms
                logging.info(f"Searching for video with query: {query}")
                url, video_duration = getBestVideo(query, orientation_landscape=not self._db_format_vertical, used_vids=used_links)
                if url:
                    video_start_time = current_time  # Start at the current cumulative time
                    video_end_time = video_start_time + video_duration  # Calculate the end time
                    used_links.append(url.split('.hd')[0])
                    timed_video_urls.append([[video_start_time, video_end_time], url])
                    current_time = video_end_time  # Update current time to the end of this video
                    logging.info(f"Video found: {url} with duration {video_duration} seconds")

            self._db_timed_video_urls = timed_video_urls
            logging.info(f"Generated video URLs: {timed_video_urls}")

        except Exception as e:
            logging.error(f"Error in _generateVideoUrls: {e}")
            raise

    def _chooseBackgroundMusic(self):
        logging.info("Starting _chooseBackgroundMusic step...")
        if self._db_background_music_name:
            self._db_background_music_url = AssetDatabase.get_asset_link(self._db_background_music_name)
            logging.info(f"Background music selected: {self._db_background_music_url}")

    def _prepareBackgroundAssets(self):
        logging.info("Starting _prepareBackgroundAssets step...")
        self.verifyParameters(voiceover_audio_url=self._db_audio_path)
        if not self._db_voiceover_duration:
            self.logger("Rendering short: (1/4) preparing voice asset...")
            self._db_audio_path, self._db_voiceover_duration = get_asset_duration(
                self._db_audio_path, isVideo=False)
            logging.info(f"Voiceover duration: {self._db_voiceover_duration}")

    def _prepareCustomAssets(self):
        logging.info("Starting _prepareCustomAssets step...")
        self.logger("Rendering short: (3/4) preparing custom assets...")
        pass

    def _editAndRenderShort(self):
        logging.info("Starting _editAndRenderShort step...")
        self.verifyParameters(
            voiceover_audio_url=self._db_audio_path)

        outputPath = self.dynamicAssetDir+"rendered_video.mp4"
        if not (os.path.exists(outputPath)):
            self.logger("Rendering short: Starting automated editing...")
            videoEditor = EditingEngine()
            videoEditor.addEditingStep(EditingStep.ADD_VOICEOVER_AUDIO, {
                                       'url': self._db_audio_path})
            if (self._db_background_music_url):
                videoEditor.addEditingStep(EditingStep.ADD_BACKGROUND_MUSIC, {'url': self._db_background_music_url,
                                                                              'loop_background_music': self._db_voiceover_duration,
                                                                              "volume_percentage": 0.08})
            for (t1, t2), video_url in self._db_timed_video_urls:
                videoEditor.addEditingStep(EditingStep.ADD_BACKGROUND_VIDEO, {'url': video_url,
                                                                              'set_time_start': t1,
                                                                              'set_time_end': t2})
            if (self._db_format_vertical):
                caption_type = EditingStep.ADD_CAPTION_SHORT_ARABIC if self._db_language == Language.ARABIC.value else EditingStep.ADD_CAPTION_SHORT
            else:
                caption_type = EditingStep.ADD_CAPTION_LANDSCAPE_ARABIC if self._db_language == Language.ARABIC.value else EditingStep.ADD_CAPTION_LANDSCAPE

            for (t1, t2), text in self._db_timed_captions:
                videoEditor.addEditingStep(caption_type, {'text': text.upper(),
                                                          'set_time_start': t1,
                                                          'set_time_end': t2})

            self.logger("Rendering video...")
            videoEditor.renderVideo(outputPath, logger=self.logger if self.logger is not self.default_logger else None)
            self.logger("Video rendering completed.")
            logging.info(f"Video rendered to {outputPath}")

        self._db_video_path = outputPath

    def _addMetadata(self):
        logging.info("Starting _addMetadata step...")
        if not os.path.exists('videos/'):
            os.makedirs('videos')
        self._db_yt_title, self._db_yt_description = gpt_yt.generate_title_description_dict(self._db_script)
        logging.info(f"Generated YouTube title and description: {self._db_yt_title}, {self._db_yt_description}")

        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d_%H-%M-%S")
        newFileName = f"videos/{date_str} - " + \
            re.sub(r"[^a-zA-Z0-9 '\n\.]", '', self._db_yt_title)

        shutil.move(self._db_video_path, newFileName+".mp4")
        with open(newFileName+".txt", "w", encoding="utf-8") as f:
            f.write(
                f"---Youtube title---\n{self._db_yt_title}\n---Youtube description---\n{self._db_yt_description}")
        self._db_video_path = newFileName+".mp4"
        self._db_ready_to_upload = True
        self.logger(f"Video rendered and metadata saved at {newFileName}.mp4")
        logging.info(f"Metadata saved at {newFileName}.txt")

