"""Named, hot-reloadable operations for the already authenticated XHS editor."""
import json,re
from urllib.parse import urlparse
from bilibili_fields import one

STEPS = {'inspect','cover_open','cover_upload','cover_confirm','declaration_open','declaration_select','topics','verify','submit','receipt','refresh_verification','check_notes'}

def validate(options):
    if not isinstance(options,dict) or set(options)-{'step','tags','declaration'} or options.get('step','inspect') not in STEPS:
        raise ValueError('无效的小红书表单操作')
    if 'tags' in options and (not isinstance(options['tags'],list) or len(options['tags'])>10 or any(not isinstance(t,str) or not t.strip() or len(t)>30 for t in options['tags'])): raise ValueError('话题无效')
    if options.get('declaration','none') not in {'none','笔记含AI合成内容'}: raise ValueError('声明无效')
    return options

def apply(page,job,manager):
    options=validate(job['fieldOptions'])
    if urlparse(page.url).hostname != 'creator.xiaohongshu.com': raise ValueError('当前不是小红书创作平台')
    if page.get_by_text('发布成功',exact=True).is_visible():
        manager.update(job,status='submitted',message='小红书页面确认发布成功',receiptUrl=page.url)
        manager.inspect_page(page)
        return
    if options.get('step')=='receipt':
        manager.inspect_page(page)
        text=page.locator('body').inner_text()
        if '扫码验证' in text:
            manager.update(job,status='waiting_user',message='小红书发布安全验证待扫码；保留原稿件，未重复提交',securityVerification=True)
        else:
            (manager.root/'xiaohongshu-management-link.json').write_text(json.dumps(page.get_by_text('笔记管理',exact=True).evaluate_all('(es)=>es.map(e=>({html:e.outerHTML,parent:e.parentElement.outerHTML.slice(0,4000)}))'),ensure_ascii=False,indent=2),encoding='utf-8')
            manager.update(job,status='waiting_user',message='小红书安全验证已完成，原稿件仍在编辑页；核对笔记管理后继续',securityVerification=False)
        return
    if options.get('step')=='refresh_verification':
        expired=page.get_by_text('已过期，点击二维码区域刷新',exact=True)
        if expired.count():
            (manager.root/'xiaohongshu-verification-controls.json').write_text(json.dumps(expired.evaluate_all('(es)=>es.map(e=>e.parentElement.outerHTML.slice(0,5000))'),ensure_ascii=False,indent=2),encoding='utf-8')
            one(page.locator('.qrcode-container')).click()
        page.wait_for_timeout(1000)
        manager.inspect_page(page)
        manager.update(job,status='waiting_user',message='小红书发布安全验证待扫码；二维码已刷新，原稿件保留',securityVerification=True)
        return
    title=one(page.get_by_placeholder('填写标题会有更多赞哦',exact=True))
    if title.input_value() == 'minimax'+job['title']:
        manager.update(job,titleBeforePageEdit=job['title'],title=title.input_value())
    if title.input_value()!=job['title']: raise ValueError('页面稿件与任务标题不一致')
    step=options.get('step','inspect')
    completed=dict(job.get('completedFields',{}))
    targets=options.get('tags',completed.get('topicTargets',['AI绘画','ComfyUI','人工智能','图生图','AI工具']))
    declaration=options.get('declaration',completed.get('declaration','笔记含AI合成内容'))
    if step=='check_notes':
        notes=page.context.new_page()
        try:
            notes.goto(page.url,wait_until='domcontentloaded',timeout=60000)
            one(notes.get_by_text('笔记管理',exact=True)).click()
            notes.wait_for_timeout(2500)
            text=notes.locator('body').inner_text()
            folder=manager.root/'snapshots'/'xiaohongshu-notes';folder.mkdir(parents=True,exist_ok=True)
            (folder/'page.json').write_text(json.dumps({'url':notes.url,'text':text},ensure_ascii=False,indent=2),encoding='utf-8')
            notes.screenshot(path=str(folder/'page.png'),full_page=True)
            if job['title'] in text:
                manager.update(job,status='submitted',message='小红书笔记管理已核对到本次作品',receiptUrl=notes.url,receiptSource='observed_management')
            else:
                manager.update(job,status='waiting_user',message='验证后笔记管理最新列表未发现本次标题，原编辑稿保留，可继续提交',checkedNotesAfterVerification=True)
        finally: notes.close()
        return
    elif step in {'verify','submit'}:
        editor=one(page.locator('.tiptap.ProseMirror'))
        entities=editor.locator('[data-topic-id],[data-type="topic"],[data-type="mention"],[contenteditable="false"],a[href*="topic"]').all_text_contents()
        actual=[re.sub(r'\[话题\]#?$', '',x.strip().lstrip('#')).strip() for x in entities]
        expected=targets
        if actual!=expected: raise ValueError('实际话题与目标不一致：'+str(actual))
        if not completed.get('cover'): raise ValueError('正式封面尚未确认')
        if declaration!='none': one(page.get_by_text(declaration,exact=True)).wait_for(state='visible')
        if '视频上传中' in page.locator('body').inner_text(): raise ValueError('视频仍在上传')
        completed['topicsVerified']=actual
        completed['titleVerified']=title.input_value()
        manager.update(job,completedFields=completed)
        if step=='submit':
            native=page.get_by_text('发布',exact=True)
            if native.count():
                button=one(native)
                if not button.is_enabled(): raise ValueError('发布按钮不可用')
                position=None
            else:
                button=one(page.locator('xhs-publish-btn[submit-text="发布"][is-publish="true"]'))
                if button.get_attribute('submit-disabled')!='false' or button.get_attribute('submit-loading')!='false':
                    raise ValueError('发布组件不可用')
                box=button.bounding_box()
                # Verified 680px footer: two centered 120px buttons separated by 24px.
                # Closed shadow DOM exposes no inner locator; use its native hit target.
                if abs(box['width']-680)>1 or abs(box['height']-90)>1: raise ValueError('发布组件布局变化，须先核对截图')
                manager.inspect_page(page)
                position={'x':box['width']/2+72,'y':box['height']/2}
            manager.update(job,status='submitting',message='已开始提交小红书，等待回执')
            button.click(position=position)
            page.get_by_text(re.compile(r'^(笔记)?发布成功[！!。]?$')).first.wait_for(state='visible',timeout=45000)
            manager.inspect_page(page)
            manager.update(job,status='submitted',message='小红书平台确认发布成功，等待审核',receiptUrl=page.url,receiptSource='observed_page')
            return
    elif step=='topics':
        editor=one(page.locator('.tiptap.ProseMirror'))
        editor.click();page.keyboard.press('Control+End')
        for tag in targets:
            page.keyboard.type(' #'+tag,delay=60)
            dropdown=page.locator('#creator-editor-topic-container')
            dropdown.wait_for(state='visible',timeout=12000)
            one(dropdown.get_by_text(re.compile(r'^#?'+re.escape(tag)+r'$'))).click()
            page.keyboard.press('Space')
        page.keyboard.press('Escape')
        completed['topics']=editor.locator('[data-topic-id],[data-type="topic"],[data-type="mention"],[contenteditable="false"],a[href*="topic"]').all_text_contents()
        completed['topicTargets']=targets
    elif step=='cover_open':
        page.locator('.cover-plugin-preview .cover > .default').hover()
        one(page.locator('.cover-edit-entry')).click()
    elif step=='cover_upload':
        inputs=page.locator('input[type=file][accept*="image"]')
        if inputs.count()!=1: raise ValueError('图片上传控件不唯一')
        inputs.set_input_files(str(manager.asset(job['coverId'])))
    elif step=='cover_confirm':
        one(page.get_by_text('完成',exact=True)).click()
        completed['cover']=job['coverId']
    elif step=='declaration_open':
        one(page.get_by_text('添加内容类型声明',exact=True)).click()
    elif step=='declaration_select':
        one(page.get_by_text('笔记含AI合成内容',exact=True)).click()
        completed['declaration']='笔记含AI合成内容'
    # DOM-only diagnostics, no session or credential data.
    details=page.locator('input[type=file],[role=dialog]').evaluate_all('(es)=>es.map(e=>({tag:e.tagName,accept:e.accept,html:e.outerHTML.slice(0,18000),parent:e.parentElement.outerHTML.slice(0,22000)}))')
    (manager.root/'xiaohongshu-submit-controls.json').write_text(json.dumps({'frames':[{'url':f.url,'name':f.name,'text':f.locator('body').inner_text()[-1000:],'buttons':f.locator('button').evaluate_all('(es)=>es.map(e=>e.outerHTML.slice(0,1500))')} for f in page.frames],'publish':page.get_by_text('发布',exact=True).evaluate_all('(es)=>es.map(e=>({html:e.outerHTML,parent:e.parentElement.outerHTML,visible:!!e.getClientRects().length}))'),'iframe':page.locator('iframe').evaluate_all('(es)=>es.map(e=>e.outerHTML.slice(0,1500))')},ensure_ascii=False,indent=2),encoding='utf-8')
    (manager.root/'xiaohongshu-controls.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
    (manager.root/'xiaohongshu-footer-dom.json').write_text(json.dumps({'hostBox':page.locator('xhs-publish-btn').bounding_box(),'html':page.locator('xhs-publish-btn').evaluate('(e)=>e.outerHTML'),'shadowOpen':page.locator('xhs-publish-btn').evaluate('(e)=>!!e.shadowRoot')},ensure_ascii=False,indent=2),encoding='utf-8')
    elements=page.get_by_text('设置封面',exact=True).evaluate_all('(es)=>es.map(e=>e.parentElement.parentElement.outerHTML.slice(0,24000))')
    (manager.root/'xiaohongshu-cover.json').write_text(json.dumps(elements,ensure_ascii=False,indent=2),encoding='utf-8')
    manager.inspect_page(page)
    manager.update(job,status='waiting_user',message='小红书表单操作已完成，页面快照已更新',completedFields=completed)
