"""Named operations executed by the Douyin Playwright owner thread."""
import json,re
from urllib.parse import urlparse, parse_qs
from bilibili_fields import one

def validate(options):
    if not isinstance(options,dict) or set(options)-{'step','coverId','tags','declaration'} or options.get('step','inspect') not in {'inspect','cover_open','cover_upload','cover_confirm','declaration_open','declaration_select','topics','topics_select','topics_replace','cover_vertical_open','verify','submit','receipt'}:
        raise ValueError('无效的抖音表单操作')
    if 'tags' in options and (not isinstance(options['tags'],list) or len(options['tags'])>10 or any(not isinstance(t,str) or not t.strip() or len(t)>30 for t in options['tags'])): raise ValueError('话题无效')
    if options.get('declaration','none') not in {'none','内容由AI生成'}: raise ValueError('声明无效')
    return options

def apply(page,job,manager):
    import importlib,live_receipts
    importlib.reload(live_receipts).install(manager)
    options=validate(job['fieldOptions'])
    if urlparse(page.url).hostname!='creator.douyin.com': raise ValueError('当前不是抖音创作平台')
    if options.get('step')=='receipt':
        manager.inspect_page(page)
        return
    query=parse_qs(urlparse(page.url).query)
    if query.get('enter_from')==['edit_item'] and re.fullmatch(r'\d+',query.get('mid',[''])[0]) and page.get_by_text('作品修改审核中，暂不支持修改',exact=True).is_visible():
        manager.inspect_page(page)
        manager.update(job,status='submitted',message='抖音已有作品，页面显示：作品修改审核中，暂不支持修改；封面展示待审核后核对',
                       receiptUrl=page.url,platformItemId=query['mid'][0],receiptSource='observed_edit_page')
        return
    if one(page.get_by_placeholder(re.compile('标题'))).input_value()!=job['title']:
        raise ValueError('页面标题与任务不一致')
    step=options.get('step','inspect')
    targets=options.get('tags',job.get('completedFields',{}).get('topicTargets',['AI绘画','ComfyUI','人工智能','图生图','AI工具']))
    declaration=options.get('declaration',job.get('completedFields',{}).get('declaration','内容由AI生成'))
    if step in {'verify','submit'}:
        editor=one(page.locator('div.zone-container[contenteditable="true"]'))
        actual=[x.strip().lstrip('#') for x in editor.locator('[data-mention="#"]').all_text_contents()]
        expected=targets
        if len(actual)!=len(expected) or set(actual)!=set(expected): raise ValueError('话题未完整保存')
        plain=editor.evaluate('(e)=>{const c=e.cloneNode(true);c.querySelectorAll("[data-mention]").forEach(n=>n.remove());return c.textContent}')
        normalize=lambda value:re.sub(r'[\s\u200b\xa0]+','',value)
        if normalize(plain)!=normalize(job['description']): raise ValueError('正文与原稿不一致')
        if declaration!='none': one(page.get_by_text(declaration,exact=True)).wait_for(state='visible')
        covers=[]
        for label in ('横封面4:3','竖封面3:4'):
            card=one(page.get_by_text(label,exact=True)).locator('xpath=../..')
            img=card.locator('img')
            if img.count()!=1 or not img.evaluate('(e)=>e.complete && e.naturalWidth>0'): raise ValueError(label+'预览未加载')
            covers.append(urlparse(img.get_attribute('src')).path)
        if covers[0]==covers[1]: raise ValueError('横竖封面未分别保存')
        if '横/竖双封面缺失' in page.locator('body').inner_text(): raise ValueError('平台仍提示双封面缺失')
        manager.update(job,completedFields={**job.get('completedFields',{}),'topicsVerified':actual,'bodyVerified':True,'declaration':declaration,'coversVerified':['4:3','3:4']})
        if step=='submit':
            button=one(page.get_by_role('button',name='发布',exact=True))
            if not button.is_enabled(): raise ValueError('发布按钮不可用')
            manager.inspect_page(page)
            manager.update(job,status='submitting',message='已开始提交抖音，等待平台回执')
            button.click()
            page.wait_for_function("() => document.body.innerText.includes('发布成功') || location.pathname.includes('/content/manage')",timeout=45000)
            page.wait_for_timeout(1500)
            text=page.locator('body').inner_text()
            if '发布成功' not in text and job['title'] not in text: raise ValueError('提交后尚未核对到作品记录')
            manager.inspect_page(page)
            manager.update(job,status='submitted',message='抖音平台已确认提交，作品记录已核对',receiptUrl=page.url,receiptSource='observed_page')
            return
    notice=page.get_by_text('我知道了',exact=True)
    if step not in {'inspect','cover_upload'} and notice.count() and notice.is_visible(): notice.click()
    if step=='topics_replace':
        editor=one(page.locator('div.zone-container[contenteditable="true"]'))
        editor.fill(job['description']);editor.press('Control+End')
        for tag in targets:
            page.keyboard.type(' #'+tag,delay=70)
            candidate=page.locator('[class^="tag-hash-view-name-"]').filter(has_text=re.compile('^'+re.escape(tag)+'$'))
            one(candidate).click()
            page.keyboard.press('ArrowRight');page.keyboard.press('Space')
        page.keyboard.press('Escape')
        actual=[x.strip().lstrip('#') for x in editor.locator('[data-mention="#"]').all_text_contents()]
        if len(actual)!=len(targets) or set(actual)!=set(targets): raise ValueError('话题实体不一致：'+str(actual))
        plain=editor.evaluate('(e)=>{const c=e.cloneNode(true);c.querySelectorAll("[data-mention]").forEach(n=>n.remove());return c.textContent}')
        normalize=lambda value:re.sub(r'[\s\u200b\xa0]+','',value)
        if normalize(plain)!=normalize(job['description']): raise ValueError('正文回读与原稿不一致')
        manager.update(job,completedFields={**job.get('completedFields',{}),'topicsVerified':actual,'topicTargets':targets,'bodyVerified':True})
    elif step=='topics':
        editor=one(page.locator('div.zone-container[contenteditable="true"]'))
        editor.click();page.keyboard.press('Control+End')
        page.keyboard.type(' #AI绘画',delay=80)
        page.wait_for_timeout(1200)
    elif step=='topics_select':
        editor=one(page.locator('div.zone-container[contenteditable="true"]'))
        for tag in ['AI绘画','ComfyUI','人工智能','图生图','AI工具']:
            entities=[x.strip().lstrip('#') for x in editor.locator('[data-mention="#"]').all_text_contents()]
            if tag in entities: continue
            candidate=page.locator('[class^="tag-hash-view-name-"]').filter(has_text=re.compile('^'+re.escape(tag)+'$'))
            if not candidate.count():
                editor.click();page.keyboard.press('Control+End')
                page.keyboard.type(' #'+tag,delay=70)
            one(candidate).click()
            page.wait_for_timeout(250)
        page.keyboard.press('Escape')
        actual=[x.strip().lstrip('#') for x in editor.locator('[data-mention="#"]').all_text_contents()]
        if len(actual)!=5 or set(actual)!=set(['AI绘画','ComfyUI','人工智能','图生图','AI工具']): raise ValueError('话题实体不一致：'+str(actual))
        manager.update(job,completedFields={**job.get('completedFields',{}),'topicsVerified':actual})
    elif step=='cover_open':
        page.get_by_text('选择封面',exact=True).filter(visible=True).first.click()
    elif step=='cover_upload':
        upload=page.locator('.semi-upload.upload-BvM5FF > input.semi-upload-hidden-input')
        if upload.count()!=1: raise ValueError('封面文件控件不唯一')
        upload.set_input_files(str(manager.asset(options.get('coverId') or job['coverId'])))
        page.wait_for_timeout(1500)
    elif step=='cover_vertical_open':
        page.get_by_text('设置竖封面',exact=True).filter(visible=True).last.click()
    elif step=='cover_confirm':
        one(page.get_by_text('完成',exact=True)).click()
    elif step=='declaration_open':
        one(page.get_by_text('请选择自主声明',exact=True)).click()
    elif step=='declaration_select':
        radio=one(page.locator('label.semi-radio').filter(has_text='内容由AI生成'))
        if 'semi-radio-checked' not in (radio.get_attribute('class') or ''): radio.click()
        page.wait_for_function("() => [...document.querySelectorAll('label.semi-radio-checked')].some(e=>e.textContent.trim()==='内容由AI生成')",timeout=10000)
        one(page.get_by_text('确定',exact=True)).click()
        manager.update(job,completedFields={**job.get('completedFields',{}),'declaration':'内容由AI生成'})
    details=page.locator('input[type=file],[role=dialog]').evaluate_all('(es)=>es.map(e=>({tag:e.tagName,accept:e.accept,html:e.outerHTML.slice(0,14000),parent:e.parentElement.outerHTML.slice(0,22000)}))')
    (manager.root/'douyin-editor-dom.json').write_text(json.dumps(page.locator('div.zone-container[contenteditable="true"]').evaluate_all('(es)=>es.map(e=>e.outerHTML)'),ensure_ascii=False,indent=2),encoding='utf-8')
    (manager.root/'douyin-topic-controls.json').write_text(json.dumps(page.get_by_text('#ComfyUI',exact=True).evaluate_all('(es)=>es.map(e=>({html:e.outerHTML,parent:e.parentElement.outerHTML.slice(0,2500),grandparent:e.parentElement.parentElement.outerHTML.slice(0,5000)}))'),ensure_ascii=False,indent=2),encoding='utf-8')
    (manager.root/'douyin-declaration-controls.json').write_text(json.dumps(page.get_by_text('内容由AI生成',exact=True).evaluate_all('(es)=>es.map(e=>({html:e.outerHTML,parent:e.parentElement.outerHTML.slice(0,5000),grandparent:e.parentElement.parentElement.outerHTML.slice(0,7000)}))'),ensure_ascii=False,indent=2),encoding='utf-8')
    (manager.root/'douyin-saved-cover-controls.json').write_text(json.dumps({label:page.get_by_text(label,exact=True).evaluate_all('(es)=>es.map(e=>e.parentElement.parentElement.outerHTML.slice(0,9000))') for label in ('横封面4:3','竖封面3:4')},ensure_ascii=False,indent=2),encoding='utf-8')
    (manager.root/'douyin-submit-controls.json').write_text(json.dumps(page.get_by_text('发布',exact=True).evaluate_all('(es)=>es.map(e=>({html:e.outerHTML,parent:e.parentElement.outerHTML.slice(0,2500)}))'),ensure_ascii=False,indent=2),encoding='utf-8')
    (manager.root/'douyin-controls.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
    manager.inspect_page(page)
    manager.update(job,status='waiting_user',message='抖音表单操作完成，页面快照已更新')
