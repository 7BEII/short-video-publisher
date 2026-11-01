"""Local publishing workbench; connects to the existing 8772 media worker."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import secrets
from threading import Lock
from urllib.parse import quote

import requests
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

ROOT = Path(__file__).resolve().parent
BRIDGE = 'http://127.0.0.1:8772'
SUPPORTED = {'douyin': (30, 1000), 'bilibili': (80, 2000), 'xiaohongshu': (20, 1000)}
VIDEO_EXTS = {'.mp4', '.mov', '.webm'}
COVER_EXTS = {'.jpg', '.jpeg', '.png'}
MAX_VIDEO = 2 * 1024 ** 3
MAX_COVER = 20 * 1024 ** 2


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=MAX_VIDEO + MAX_COVER + 1024 * 1024)
    csrf = secrets.token_urlsafe(32)
    http = requests.Session()
    http.trust_env = False
    prepare_locks = {name: Lock() for name in SUPPORTED}

    @app.before_request
    def local_only():
        host = request.host.split(':', 1)[0].lower()
        if host not in {'127.0.0.1', 'localhost'} or request.remote_addr not in {'127.0.0.1', '::1'}:
            return jsonify(error='仅允许本机访问'), 403
        if request.method != 'GET':
            origin = request.headers.get('Origin', '')
            if origin != request.host_url.rstrip('/') or not secrets.compare_digest(request.headers.get('X-App-Token', ''), csrf):
                return jsonify(error='请求校验失败，请刷新页面'), 403

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_):
        return jsonify(error='素材超过大小限制'), 413

    def get_bridge(path, timeout=8):
        response = http.get(BRIDGE + path, timeout=timeout)
        response.raise_for_status()
        return response.json()

    def post_bridge(path, **kwargs):
        token = get_bridge('/api/config')['token']
        headers = kwargs.pop('headers', {})
        headers['X-Reader-Token'] = token
        response = http.post(BRIDGE + path, headers=headers, timeout=300, **kwargs)
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not response.ok:
            raise ValueError(body.get('error') or f'发布服务错误 {response.status_code}')
        return body

    def asset(stream, extensions, limit):
        name = Path(stream.filename or '').name
        ext = Path(name).suffix.lower()
        if ext not in extensions:
            raise ValueError('素材格式不支持：' + name)
        digest = hashlib.sha256()
        size = 0
        while chunk := stream.stream.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise ValueError('素材超过大小限制')
            digest.update(chunk)
        if not size:
            raise ValueError('素材为空')
        stream.stream.seek(0)
        return name, digest.hexdigest() + ext

    @app.get('/')
    def index():
        return send_from_directory(ROOT / 'ui', 'index.html')

    @app.get('/api/config')
    def config():
        return jsonify(token=csrf, supported=list(SUPPORTED))

    @app.get('/api/status')
    def status():
        try:
            data = get_bridge('/api/media/status')
            return jsonify(available=True, accounts=data.get('accounts', {}), jobs=data.get('jobs', []))
        except (requests.RequestException, ValueError, KeyError):
            return jsonify(available=False, message='本机 8772 发布服务未连接')

    @app.post('/api/login')
    def login():
        data = request.get_json(silent=True) or {}
        platform = data.get('platform')
        if platform not in SUPPORTED:
            return jsonify(error='该渠道尚未接入'), 400
        try:
            post_bridge('/api/media/login', json={'platform': platform})
            return jsonify(message='已请求打开平台登录窗口；请在窗口中验证登录')
        except (requests.RequestException, ValueError, KeyError) as exc:
            return jsonify(error=str(exc) if isinstance(exc, ValueError) else '无法连接本机 8772 发布服务'), 502

    @app.post('/api/prepare')
    def prepare():
        platform = request.form.get('platform', '')
        title = request.form.get('title', '').strip()
        body = request.form.get('body', '').strip()
        if platform not in SUPPORTED:
            return jsonify(error='该渠道尚未接入'), 400
        title_limit, body_limit = SUPPORTED[platform]
        if not title or len(title) > title_limit or len(body) > body_limit:
            return jsonify(error='请检查标题和正文长度'), 400
        video = request.files.get('video')
        cover = request.files.get('cover')
        if not video or not cover:
            return jsonify(error='请选择正式视频和封面'), 400
        try:
            video_name, video_id = asset(video, VIDEO_EXTS, MAX_VIDEO)
            cover_name, _ = asset(cover, COVER_EXTS, MAX_COVER)
            def upload_file(file, name):
                file.stream.seek(0, os.SEEK_END)
                size = file.stream.tell()
                file.stream.seek(0)
                return post_bridge('/api/media/upload', data=file.stream,
                    headers={'X-Filename': quote(name), 'Content-Length': str(size)})['assetId']
            with prepare_locks[platform]:
                state = get_bridge('/api/media/status')
                if state.get('accounts', {}).get(platform, {}).get('status') != 'connected':
                    raise ValueError('请先验证该平台登录状态')
                for old in state.get('jobs', []):
                    if old.get('platform') == platform and old.get('assetId') == video_id:
                        raise ValueError('此平台已有相同视频任务，请在原发布工作台检查并继续，避免重复上传')
                uploaded_video = upload_file(video, video_name)
                cover_id = upload_file(cover, cover_name)
                job = post_bridge('/api/media/publish', json={'platform': platform, 'title': title,
                    'body': body, 'tags': request.form.get('tags', ''), 'assetId': uploaded_video,
                    'coverId': cover_id, 'mode': 'prepare'})
            return jsonify(jobId=job['id'], status=job.get('status', 'queued'),
                           message='任务已排队，正在准备平台稿件；请在原发布工作台核对并提交')
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except (requests.RequestException, KeyError):
            return jsonify(error='本机发布服务不可用或连接中断；请先检查原工作台，避免重复操作'), 502

    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8788)
    args = parser.parse_args()
    print(f'短视频发布平台：http://127.0.0.1:{args.port}', flush=True)
    create_app().run(host='127.0.0.1', port=args.port, threaded=True, use_reloader=False)
