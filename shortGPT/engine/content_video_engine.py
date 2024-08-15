import datetime
import os
import re
import shutil
import cv2
import logging

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
        logging.info("Step 1 _generateTempAudio")
        if not self._db_script:
            raise NotImplementedError("generateScript method must set self._db_script.")
        if self._db_temp_audio_path:
            return
        self.verifyParameters(text=self._db_script)
        script = self._db_script
        if self._db_language != Language.ENGLISH.value:
            self._db_translated_script = gpt_translate.translateContent(script, self._db_language)
            script = self._db_translated_script
        self._db_temp_audio_path = self.voiceModule.generate_voice(
            script, self.dynamicAssetDir + "temp_audio_path.wav")

    def _speedUpAudio(self):
        logging.info("Step 2 _speedUpAudio")
        if self._db_audio_path:
            return
        self.verifyParameters(tempAudioPath=self._db_temp_audio_path)
        self._db_audio_path = self._db_temp_audio_path

    def _timeCaptions(self):
        logging.info("Step 3 _timeCaptions")
        self.verifyParameters(audioPath=self._db_audio_path)
        whisper_analysis = audio_utils.audioToText(self._db_audio_path)
        max_len = 15
        if not self._db_format_vertical:
            max_len = 30
        self._db_timed_captions = captions.getCaptionsWithTime(
            whisper_analysis, maxCaptionSize=max_len)

    def _generateVideoSearchTerms(self):
        logging.info("Step 4 _generateVideoSearchTerms")
        self.verifyParameters(captionsTimed=self._db_timed_captions)
        self._db_timed_video_searches = [
            [[0, 9999], ["drone", "military drone", "war"]]
        ]

    def _generateVideoUrls(self):
        logging.info("Step 5 _generateVideoUrls")
        timed_video_urls = []
        used_links = []
        current_time = 0  # Track the cumulative time to set proper start times

        # Ensure that the voiceover duration is calculated
        if not self._db_voiceover_duration:
            self._prepareBackgroundAssets()

        while current_time < self._db_voiceover_duration:
            for query in self._db_timed_video_searches[0][1]:
                result = getBestVideo(query, orientation_landscape=not self._db_format_vertical, used_vids=used_links)
                
                if isinstance(result, tuple) and len(result) == 2:
                    url, video_duration = result
                elif isinstance(result, str):  # If only URL is returned
                    url = result
                    video_duration = self.get_video_duration_from_url(url)
                else:
                    logging.error(f"Unexpected result format from getBestVideo: {result}")
                    continue

                if url:
                    video_start_time = current_time  # Start at the current cumulative time
                    video_end_time = video_start_time + video_duration  # Calculate the end time
                    used_links.append(url.split('.hd')[0])
                    timed_video_urls.append([[video_start_time, video_end_time], url])
                    logging.info(f"Added video from {video_start_time} to {video_end_time} using URL {url}")
                    current_time = video_end_time  # Update current time to the end of this video

                    if current_time >= self._db_voiceover_duration:
                        break

        self._db_timed_video_urls = timed_video_urls
        logging.info(f"Generated video URLs: {self._db_timed_video_urls}")

    def get_video_duration_from_url(self, url):
        logging.info(f"Downloading video from URL: {url}")
        local_filename = url.split('/')[-1]
        output_path = os.path.join(self.dynamicAssetDir, local_filename)
        
        # Download the video
        os.system(f'wget {url} -O {output_path}')
        
        # Use cv2 to get the duration
        cap = cv2.VideoCapture(output_path)
        if not cap.isOpened():
            logging.error(f"Failed to open video file: {output_path}")
            return 0

        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps
        
        logging.info(f"Video duration from {url}: {duration} seconds")
        cap.release()
        
        return duration

    def _chooseBackgroundMusic(self):
        logging.info("Step 6 _chooseBackgroundMusic")
        if self._db_background_music_name:
            self._db_background_music_url = AssetDatabase.get_asset_link(self._db_background_music_name)

    def _prepareBackgroundAssets(self):
        logging.info("Step 7 _prepareBackgroundAssets")
        self.verifyParameters(voiceover_audio_url=self._db_audio_path)
        if not self._db_voiceover_duration:
            logging.info("Rendering short: (1/4) preparing voice asset...")
            self._db_audio_path, self._db_voiceover_duration = get_asset_duration(
                self._db_audio_path, isVideo=False)

    def _prepareCustomAssets(self):
        logging.info("Step 8 _prepareCustomAssets")
        logging.info("Rendering short: (3/4) preparing custom assets...")
        pass

    def _editAndRenderShort(self):
        logging.info("Step 9 _editAndRenderShort")
        self.verifyParameters(
            voiceover_audio_url=self._db_audio_path)

        outputPath = self.dynamicAssetDir+"rendered_video.mp4"
        if not (os.path.exists(outputPath)):
            logging.info("Rendering short: Starting automated editing...")
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
                logging.info(f"Added video {video_url} from {t1} to {t2}")
            if (self._db_format_vertical):
                caption_type = EditingStep.ADD_CAPTION_SHORT_ARABIC if self._db_language == Language.ARABIC.value else EditingStep.ADD_CAPTION_SHORT
            else:
                caption_type = EditingStep.ADD_CAPTION_LANDSCAPE_ARABIC if self._db_language == Language.ARABIC.value else EditingStep.ADD_CAPTION_LANDSCAPE

            for (t1, t2), text in self._db_timed_captions:
                videoEditor.addEditingStep(caption_type, {'text': text.upper(),
                                                          'set_time_start': t1,
                                                          'set_time_end': t2})

            logging.info("Rendering video...")
            videoEditor.renderVideo(outputPath, logger=logging.info)
            logging.info("Video rendering completed.")

        self._db_video_path = outputPath

    def _addMetadata(self):
        logging.info("Step 10 _addMetadata")
        if not os.path.exists('videos/'):
            os.makedirs('videos')
        self._db_yt_title, self._db_yt_description = gpt_yt.generate_title_description_dict(self._db_script)

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
        logging.info(f"Video rendered and metadata saved at {newFileName}.mp4")
