import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from editor import cache, review
import app as server

WORDS = [{"word": "Olá", "start": 0.2, "end": 0.6, "emph": True}]

class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = Path(self.temp.name)/"source.mp4"
        self.source.write_bytes(b"source")
        self.params = {"video": str(self.source), "whisper_model": "small"}
    def tearDown(self):
        self.temp.cleanup()
    def test_transcript_reused_and_invalidated_for_model_language_or_source(self):
        def extract(source, dest, **kwargs): Path(dest).write_bytes(b"audio")
        with patch.object(cache.transcribe, "extract_wav", side_effect=extract) as audio, patch.object(cache.transcribe, "transcribe_words", return_value=(WORDS,"pt")) as whisper:
            self.assertEqual(cache.words(self.params,1)[0], WORDS)
            self.assertEqual(cache.words(self.params,1)[0], WORDS)
            self.assertEqual(whisper.call_count, 1)
            cache.words(self.params|{"whisper_model":"base"},1)
            cache.words(self.params|{"language":"en"},1)
            self.assertEqual(whisper.call_count,3)
            self.assertEqual(audio.call_count,1)
            self.source.write_bytes(b"different source")
            cache.words(self.params,1)
            self.assertEqual(whisper.call_count,4)
            self.assertEqual(audio.call_count,2)
    def test_override_and_empty_override_never_load_model_or_extract_audio(self):
        with patch.object(cache.transcribe,"extract_wav") as audio, patch.object(cache.transcribe,"transcribe_words") as whisper:
            self.assertTrue(cache.words(self.params|{"words_override":WORDS},1)[0][0]["emph"])
            self.assertEqual(cache.words(self.params|{"words_override":[]},1)[0],[])
            audio.assert_not_called(); whisper.assert_not_called()
    def test_failed_transcription_does_not_poison_cache(self):
        with patch.object(cache,"audio",return_value=self.source), patch.object(cache.transcribe,"transcribe_words",side_effect=[RuntimeError("interrupted"),(WORDS,"pt")]) as whisper:
            with self.assertRaises(RuntimeError): cache.words(self.params,1)
            self.assertEqual(cache.words(self.params,1)[0],WORDS)
            self.assertEqual(whisper.call_count,2)
    def test_review_reuses_preview_and_transcript(self):
        def render(args, **kwargs): Path(args[-1]).write_bytes(b"preview")
        with patch.object(review,"probe",return_value={"has_video":True,"has_audio":True,"width":360,"height":640,"duration":2}), patch.object(cache,"words",return_value=(WORDS,"pt")), patch.object(review,"run_ffmpeg",side_effect=render) as ffmpeg:
            for n in (1,2):
                result=review.process(Path(self.temp.name)/str(n),self.params,lambda *a:None,threading.Event())
            self.assertEqual(ffmpeg.call_count,1)
            self.assertTrue(result["lines"][0]["words"][0]["emph"])

class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.ws=patch.object(server,"WORKSPACE",self.root);self.ws.start()
        self.jobs=patch.object(server,"JOBS",{});self.jobs.start()
        self.queue=patch.object(server.QUEUE,"put");self.queue.start()
        self.client=server.app.test_client()
    def tearDown(self):
        self.queue.stop();self.jobs.stop();self.ws.stop();self.temp.cleanup()
    def create(self):
        res=self.client.post('/api/jobs',data={"video":(io.BytesIO(b"fakevideo"),"example.mp4"),"images":(io.BytesIO(b"image"),"image.png"),"music":(io.BytesIO(b"audio"),"music.mp3"),"options":json.dumps({"api_key":"never-persist-me"}),"words":json.dumps(WORDS)})
        self.assertEqual(res.status_code,200,res.data)
        return res.json['id']
    def test_restart_retains_source_edits_and_assets_without_secret(self):
        ident=self.create();job=server.JOBS[ident]
        self.assertNotIn("never-persist-me",(Path(job['dir'])/'job.json').read_text())
        lines=review.build_lines(WORDS);lines[0]['words'][0]['word']='Corrigida'
        res=self.client.put('/api/jobs/'+ident+'/project',json={"lines":lines,"preferences":{"font":"Georgia","api_key":"never-persist-me"}})
        self.assertEqual(res.status_code,200)
        server.JOBS.clear();server._load_jobs()
        res=self.client.get('/api/jobs/'+ident+'/project')
        self.assertEqual(res.json['lines'][0]['words'][0]['word'],'Corrigida')
        self.assertNotIn('api_key',res.json['preferences'])
        self.assertEqual(res.json['job']['status'],'interrupted')
        child=self.client.post('/api/jobs',data={"reuse_job":ident}).json['id']
        params=server.JOBS[child]['params']
        self.assertEqual(params['video'],job['params']['video'])
        self.assertEqual(params['images'],job['params']['images'])
        self.assertEqual(params['music'],job['params']['music'])
        self.assertEqual(params['words_override'][0]['word'],'Corrigida')
        self.assertEqual(len(self.client.get('/api/projects').json),1)
    def test_removing_all_captions_images_and_music_is_preserved(self):
        ident=self.create()
        self.client.put('/api/jobs/'+ident+'/project',json={'lines':[]})
        res=self.client.post('/api/jobs',data={'reuse_job':ident,'retain_images':'[]','remove_music':'1'})
        params=server.JOBS[res.json['id']]['params']
        self.assertEqual(params['words_override'],[])
        self.assertEqual(params['images'],[])
        self.assertIsNone(params['music'])
    def test_reject_bad_times_without_replacing_saved_draft(self):
        ident=self.create();lines=review.build_lines(WORDS)
        self.client.put('/api/jobs/'+ident+'/project',json={'lines':lines})
        lines[0]['end']=-1
        self.assertEqual(self.client.put('/api/jobs/'+ident+'/project',json={'lines':lines}).status_code,400)
        self.assertEqual(self.client.get('/api/jobs/'+ident+'/project').json['lines'][0]['end'],.6)
    def test_timeline_serves_only_ready_assets_and_strips_paths(self):
        ident=self.create();work=Path(server.JOBS[ident]['dir'])/'work'
        self.assertFalse(self.client.get('/api/jobs/'+ident+'/timeline').json['ready'])
        cache.write_json(work/'timeline.json',{'duration':2,'images':[{'path':server.JOBS[ident]['params']['images'][0],'start':0,'duration':1}]})
        data=self.client.get('/api/jobs/'+ident+'/timeline').json
        self.assertTrue(data['ready']);self.assertNotIn('path',data['images'][0])
        with self.client.get(data['images'][0]['url']) as response:
            self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get('/api/jobs/'+ident+'/media/element/99').status_code,404)

if __name__=='__main__': unittest.main()
