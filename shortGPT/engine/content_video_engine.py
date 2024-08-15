import datetime
import os
import re
import shutil
import logging
from typing import Generator, Tuple, Any

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

    def __init__(self, voiceModule: VoiceModule, script: str, background_music_name: str = "", id: str = "",
                 watermark: str = None, isVerticalFormat: bool = False, language: Language = Language.ENGLISH):
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
            4: self._prepareBackgroundAssets,  # Moved this step earlier
            5: self._generateVideoSearchTerms,
            6: self._generateVideoUrls,
            7: self._chooseBackgroundMusic,
            8: self._prepareCustomAssets,
            9: self._editAndRenderShort,
            10: self._addMetadata
        }

    def makeContent(self) -> Generator[Tuple[int, str], Any, None]:
        currentStep = 1
        while currentStep <= len(self.stepDict):
            stepInfo = f"Step {currentStep}/{len(self.stepDict)}"
            try:
                self.stepDict[currentStep]()
                yield currentStep, f"{stepInfo} completed successfully"
                currentStep += 1
            except Exception as e:
                logging.error(f"Error in {stepInfo}: {str(e)}")
                yield currentStep, f"Error in {stepInfo}: {str(e)}"
                break

    def _generateTempAudio(self):
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
        if self._db_audio_path:
            return
        self.verifyParameters(tempAudioPath=self._db_temp_audio_path)
        self._db_audio_path = self._db_temp_audio_path

    def _timeCaptions(self):
        self.verifyParameters(audioPath=self._db_audio_path)
        whisper_analysis = audio_utils.audioToText(self._db_audio_path)
        max_len = 15 if self._db_format_vertical else 30
        self._db_timed_captions = captions.getCaptionsWithTime(
            whisper_analysis, maxCaptionSize=max_len)

    def _prepareBackgroundAssets(self):
        self.verifyParameters(voiceover_audio_url=self._db_audio_path)
        if not hasattr(self, '_db_voiceover_duration'):
            self.logger("Rendering short: (1/4) preparing voice asset...")
            self._db_audio_path, self._db_voiceover_duration = get_asset_duration(
                self._db_audio_path, isVideo=False)

    def _generateVideoSearchTerms(self):
        self.verifyParameters(captionsTimed=self._db_timed_captions)
        self._db_timed_video_searches = [
            [[0, 9999], ["nature landscape", "nature landscape", "nature landscape"]]
        ]

    def _generateVideoUrls(self):
        if not hasattr(self, '_db_voiceover_duration'):
            raise ValueError("Voiceover duration is not set. Ensure that _prepareBackgroundAssets is called before _generateVideoUrls.")

        timed_video_urls = []
        used_links = []
        current_time = 0
        max_attempts = 10

        logging.info(f"Starting video URL generation. Voiceover duration: {self._db_voiceover_duration}s")

        try:
            while current_time < self._db_voiceover_duration:
                logging.info(f"Current accumulated video time: {current_time}s. Looking for more clips.")
                for query in self._db_timed_video_searches[0][1]:
                    for attempt in range(max_attempts):
                        logging.info(f"Attempting to fetch video for query: {query}. Attempt {attempt + 1}/{max_attempts}.")
                        result = getBestVideo(query, orientation_landscape=not self._db_format_vertical, used_vids=used_links)
                        if result and len(result) == 2:
                            url, video_duration = result
                            video_start_time = current_time
                            video_end_time = video_start_time + video_duration
                            used_links.append(url.split('.hd')[0])
                            timed_video_urls.append([[video_start_time, video_end_time], url])
                            current_time = video_end_time
                            logging.info(f"Added video: {url} from {video_start_time}s to {video_end_time}s.")
                            break
                    else:
                        logging.error(f"Max attempts reached. Could not find video for query: {query}")
                        continue

                    if current_time >= self._db_voiceover_duration:
                        logging.info(f"Successfully gathered video clips for the entire duration: {self._db_voiceover_duration}s.")
                        break
                else:
                    logging.warning("Exhausted all queries without covering the full duration.")
                    break

            if current_time < self._db_voiceover_duration:
                logging.warning(f"Not enough video clips found. Final video will only cover {current_time}/{self._db_voiceover_duration}s.")

        except Exception as e:
            logging.error(f"Error during video URL generation: {str(e)}")
            raise

        self._db_timed_video_urls = timed_video_urls
        logging.info("Finished generating video URLs.")

    def _chooseBackgroundMusic(self):
        if self._db_background_music_name:
            self._db_background_music_url = AssetDatabase.get_asset_link(self._db_background_music_name)

    def _prepareCustomAssets(self):
        self.logger("Rendering short: (3/4) preparing custom assets...")
        pass

    def _editAndRenderShort(self):
        self.verifyParameters(voiceover_audio_url=self._db_audio_path)

        outputPath = self.dynamicAssetDir + "rendered_video.mp4"
        if not os.path.exists(outputPath):
            self.logger("Rendering short: Starting automated editing...")
            videoEditor = EditingEngine()
            videoEditor.addEditingStep(EditingStep.ADD_VOICEOVER_AUDIO, {'url': self._db_audio_path})
            
            if self._db_background_music_url:
                videoEditor.addEditingStep(EditingStep.ADD_BACKGROUND_MUSIC, {
                    'url': self._db_background_music_url,
                    'loop_background_music': self._db_voiceover_duration,
                    "volume_percentage": 0.08
                })
            
            for (t1, t2), video_url in self._db_timed_video_urls:
                videoEditor.addEditingStep(EditingStep.ADD_BACKGROUND_VIDEO, {
                    'url': video_url,
                    'set_time_start': t1,
                    'set_time_end': t2
                })
            
            caption_type = EditingStep.ADD_CAPTION_SHORT_ARABIC if self._db_language == Language.ARABIC.value else EditingStep.ADD_CAPTION_SHORT
            if not self._db_format_vertical:
                caption_type = EditingStep.ADD_CAPTION_LANDSCAPE_ARABIC if self._db_language == Language.ARABIC.value else EditingStep.ADD_CAPTION_LANDSCAPE

            for (t1, t2), text in self._db_timed_captions:
                videoEditor.addEditingStep(caption_type, {
                    'text': text.upper(),
                    'set_time_start': t1,
                    'set_time_end': t2
                })

            self.logger("Rendering video...")
            videoEditor.renderVideo(outputPath, logger=self.logger if self.logger is not self.default_logger else None)
            self.logger("Video rendering completed.")

        self._db_video_path = outputPath

    def _addMetadata(self):
        if not os.path.exists('videos/'):
            os.makedirs('videos')
        self._db_yt_title, self._db_yt_description = gpt_yt.generate_title_description_dict(self._db_script)

        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d_%H-%M-%S")
        newFileName = f"videos/{date_str} - " + re.sub(r"[^a-zA-Z0-9 '\n\.]", '', self._db_yt_title)

        shutil.move(self._db_video_path, newFileName + ".mp4")
        with open(newFileName + ".txt", "w", encoding="utf-8") as f:
            f.write(f"---Youtube title---\n{self._db_yt_title}\n---Youtube description---\n{self._db_yt_description}")
        self._db_video_path = newFileName + ".mp4"
        self._db_ready_to_upload = True
        self.logger(f"Video rendered and metadata saved at {newFileName}.mp4")
