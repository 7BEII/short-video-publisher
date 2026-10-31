"""Named Bilibili form operations, reloaded on the existing worker thread.

No arbitrary selectors or JavaScript are accepted over HTTP. Filling fields
never clicks the final submit button.
"""
import re
import json
from urllib.parse import urlparse

DECLARATIONS = {'内容无需标注', '含AI生成内容', '含虚构演绎内容', '内容含营销信息', '个人观点，仅供参考', '内容为转载'}

def validate(options):
    if not isinstance(options, dict) or set(options) - {'declaration','collection','tags','cover','step','cover43','cover169'}:
        raise ValueError('投稿字段无效')
    result = dict(options)
    if 'declaration' in result and result['declaration'] not in DECLARATIONS:
        raise ValueError('创作声明无效')
    if 'collection' in result and (not isinstance(result['collection'], str) or not 1 <= len(result['collection']) <= 100):
        raise ValueError('合集名称无效')
    if 'tags' in result:
        tags = result['tags']
        if not isinstance(tags,list) or not 1 <= len(tags) <= 10 or any(not isinstance(t,str) or not t.strip() or len(t)>20 for t in tags):
            raise ValueError('需提供 1–10 个不超过 20 字的标签')
        result['tags'] = list(dict.fromkeys(t.strip().lstrip('#') for t in tags))
        if not all(result['tags']): raise ValueError('标签不能为空')
    if 'cover' in result and not isinstance(result['cover'],bool): raise ValueError('封面设置无效')
    for key in ('cover43','cover169'):
        if key in result and (not isinstance(result[key],str) or not re.fullmatch(r'[a-f0-9]{64}\.(png|jpg|jpeg)',result[key])):
            raise ValueError('封面素材编号无效')
    if result.get('step','fill') not in {'fill','inspect','cover_open','cover_upload','cover_confirm','category_open','category_select','tags_exact','topic_open','topic_search','topic_select','receipt'}:
        raise ValueError('不支持的表单操作')
    return result

def one(locator):
    locator.filter(visible=True).first.wait_for(state='visible', timeout=10000)
    matches = [locator.nth(i) for i in range(locator.count()) if locator.nth(i).is_visible()]
    if len(matches) != 1: raise ValueError('表单控件不唯一，已保留当前稿件和页面快照')
    return matches[0]

def apply(page, job, manager):
    url = urlparse(page.url)
    if url.scheme != 'https' or url.hostname != 'member.bilibili.com' or '/upload/' not in url.path:
        raise ValueError('当前不是 B 站投稿页，未修改任何字段')
    if page.get_by_text('稿件投递成功', exact=True).is_visible():
        manager.inspect_page(page)
        links = page.locator('a[href]').evaluate_all('(es)=>es.map(e=>({text:e.innerText,url:e.href})).filter(e=>/查看进度|BV|稿件/.test(e.text+e.url))')
        manager.update(job, status='submitted', message='已观察到 B 站页面回执：稿件投递成功，等待审核',
                       receiptUrl=page.url, receiptLinks=links, receiptSource='observed_page')
        return
    if job.get('fieldOptions',{}).get('step')=='receipt':
        manager.inspect_page(page)
        return
    title = one(page.get_by_placeholder('请输入稿件标题', exact=True))
    if title.input_value() != job['title']:
        raise ValueError('页面标题与本次任务不一致，未修改其他稿件')
    options = validate(job['fieldOptions'])
    step = options.get('step', 'fill')
    completed = dict(job.get('completedFields', {}))
    if step == 'topic_open':
        one(page.get_by_text('搜索更多话题 >', exact=True)).click()
    elif step == 'topic_search':
        field=one(page.get_by_placeholder('请输入',exact=True))
        field.fill((options.get('tags') or ['ComfyUI'])[0]); field.press('Enter')
        page.wait_for_timeout(1500)
    elif step == 'topic_select':
        one(page.get_by_text((options.get('tags') or ['ComfyUI'])[0],exact=True)).click()
        one(page.get_by_text('确定',exact=True)).click()
    if step == 'category_open':
        one(page.get_by_text('娱乐', exact=True)).click()
    elif step == 'category_select':
        one(page.get_by_text('人工智能', exact=True)).click()
        completed['category'] = '人工智能'
    elif step == 'tags_exact':
        tags = options.get('tags') or job.get('completedFields', {}).get('tagsRequested', [])
        if not tags: raise ValueError('缺少目标标签')
        field = one(page.get_by_placeholder('按回车键Enter创建标签', exact=True))
        events = []
        def record_tag_response(response):
            if any(x in response.url.lower() for x in ('tag', 'label')):
                item = {'path': urlparse(response.url).path, 'status': response.status}
                try:
                    data = response.json()
                    item.update(code=data.get('code'), message=data.get('message') or data.get('msg'))
                    item['data'] = data.get('data')
                except Exception: pass
                events.append(item)
                (manager.root/'bilibili-tag-diagnostics.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
        page.on('response', record_tag_response)
        container = field.locator('xpath=../..')
        items = container.locator('.label-item-v2-container')
        removed = []
        for i in range(items.count()-1, -1, -1):
            label = items.nth(i).locator('.label-item-v2-content').inner_text().strip()
            if label not in tags:
                items.nth(i).locator('svg.close').click()
                removed.append(label)
        for tag in tags:
            label = container.locator('.label-item-v2-content').filter(has_text=re.compile('^'+re.escape(tag)+'$'))
            if not label.count():
                field.fill(''); field.press_sequentially(tag, delay=80)
                page.wait_for_timeout(800)
                events.clear()
                field.press('Enter')
                page.wait_for_timeout(1500)
                restricted = any(isinstance(e.get('data'),dict) and '话题专用' in e['data'].get('content','') for e in events)
                if restricted and not label.count():
                    one(page.get_by_text('搜索更多话题 >',exact=True)).click()
                    page.wait_for_timeout(1200)
                    search=one(page.get_by_placeholder('请输入',exact=True))
                    search.fill(tag);search.press('Enter')
                    page.wait_for_timeout(1200)
                    one(page.get_by_text(tag,exact=True)).click()
                    one(page.get_by_text('确定',exact=True)).click()
                label.wait_for(state='visible', timeout=15000)
                page.wait_for_timeout(350)
        actual = container.locator('.label-item-v2-content').all_text_contents()
        if set(actual) != set(tags): raise ValueError('实际标签与目标不一致：'+str(actual))
        completed['tagsVerified'] = actual
        completed['removedAutomaticTags'] = removed
        page.remove_listener('response',record_tag_response)
    if step == 'fill':
        if options.get('declaration'):
            field = one(page.get_by_placeholder('请选择符合您视频内容的创作声明', exact=True))
            option = page.locator('.bcc-option').filter(has_text=re.compile('^'+re.escape(options['declaration'])+'$'))
            if not any(option.nth(i).is_visible() for i in range(option.count())): field.click()
            one(option).click()
            if field.input_value() != options['declaration']:
                raise ValueError('创作声明尚未回写')
            completed['declaration'] = options['declaration']
            manager.update(job, completedFields=completed)
        if options.get('collection'):
            choice = page.get_by_text(options['collection'], exact=True)
            if not any(choice.nth(i).is_visible() for i in range(choice.count())):
                one(page.get_by_text('请选择合集', exact=True)).click()
            one(choice).click()
            completed['collection'] = options['collection']
            manager.update(job, completedFields=completed)
        if options.get('tags'):
            field = one(page.get_by_placeholder('按回车键Enter创建标签', exact=True))
            for tag in options['tags']:
                # Existing tags are preserved; stop if the platform has no capacity.
                if re.search(r'还可以添加0个标签', page.locator('body').inner_text()):
                    break
                if page.get_by_text(tag, exact=True).count(): continue
                field.fill(tag)
                field.press('Enter')
            completed['tagsRequested'] = options['tags']
            manager.update(job, completedFields=completed)
        if options.get('cover'): step = 'cover_open'
    if step == 'cover_open':
        one(page.get_by_text('添加封面', exact=True)).click()
    elif step == 'cover_upload':
        if not job.get('coverId'): raise ValueError('当前任务没有封面素材')
        inputs = page.locator('.cover-upload input[type=file]')
        inputs.first.wait_for(state='attached', timeout=10000)
        images = [inputs.nth(i) for i in range(inputs.count()) if re.search(r'image|\.png|\.jpg', inputs.nth(i).get_attribute('accept') or '')]
        if len(images) != 1: raise ValueError('无法唯一识别封面上传控件')
        cover_id = options.get('cover43') or options.get('cover169') or job['coverId']
        if options.get('cover169'):
            one(page.get_by_text('个人空间封面（16:9）', exact=True)).click()
        elif options.get('cover43'):
            one(page.get_by_text('首页推荐封面（4:3）', exact=True)).click()
        images[0].set_input_files(str(manager.asset(cover_id)))
        manager.update(job, coverId=cover_id)
    elif step == 'cover_confirm':
        one(page.get_by_text('完成', exact=True)).click()
        page.get_by_text('封面制作',exact=True).wait_for(state='hidden',timeout=30000)
        completed['cover'] = job.get('coverId')
    details = page.locator('input[type=file],input[placeholder="按回车键Enter创建标签"]').evaluate_all('(es)=>es.map(e=>({accept:e.accept,parent:e.parentElement.outerHTML.slice(0,14000),grandparent:e.parentElement.parentElement.outerHTML.slice(0,24000)}))')
    (manager.root / 'cover-controls.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
    manager.inspect_page(page)
    manager.update(job, status='editing' if job.get('automationInProgress') else 'waiting_user', completedFields=completed,
                   message='表单操作完成，页面快照已更新；尚未点击投稿')

def automate(page, job, manager):
    """Run named field operations without replacing the browser/context/page.

    Failures stay before submission. The caller owns the only final submit.
    """
    options = validate(job['bilibili'])
    job['automationInProgress'] = True
    try:
        for values in (options, {'step':'cover_upload'}, {'step':'cover_confirm'}):
            manager.update(job, status='editing', fieldOptions=values, message='自动填写 B 站稿件信息')
            apply(page,job,manager)
            if job['status'] == 'submitted': return
    finally:
        job['automationInProgress'] = False
    manager.update(job,status='waiting_user',message='B 站封面、声明、合集及标签流程完成，等待提交检查')
