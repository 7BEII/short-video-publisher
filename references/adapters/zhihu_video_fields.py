async def apply(page,job,state,action,folder):
 if action=='details':
  before=set(page.context.pages)
  await page.get_by_text('查看详情',exact=True).click();await page.wait_for_timeout(1200)
  opened=[p for p in page.context.pages if p not in before]
  url=opened[0].url if len(opened)==1 else page.url
  state['detailUrl']=url.split('?')[0]
  if url.startswith('https://www.zhihu.com/zvideo/') or url.startswith('https://www.zhihu.com/pin/'):
   state.update(status='submitted',message='知乎发布成功并取得详情链接',receiptUrl=url.split('?')[0],receiptSource='observed_page')
  return
 if action=='receipt':
  if not await page.get_by_text('发布成功',exact=True).is_visible():raise ValueError('成功回执未显示')
  entry=page.get_by_text('查看详情',exact=True)
  url=await entry.evaluate('(e)=>e.closest("a")?.href')
  if not url:
   await page.context.grant_permissions(['clipboard-read','clipboard-write'],origin='https://www.zhihu.com')
   await page.get_by_text('复制链接',exact=True).click();await page.wait_for_timeout(300)
   url=await page.evaluate('navigator.clipboard.readText()')
  if not url.startswith('https://www.zhihu.com/zvideo/'):
   from urllib.parse import urlsplit
   parsed=urlsplit(url);raise ValueError('详情地址类型：'+parsed.scheme+' '+str(parsed.hostname)+' '+parsed.path[:100])
  state.update(status='submitted',message='知乎页面确认发布成功',receiptUrl=url,receiptSource='observed_page');return
 if action in ('verify','submit'):
  import json,re
  if not (folder/'approved.json').is_file():raise ValueError('缺少用户文案确认')
  if await page.get_by_placeholder('标题',exact=True).input_value()!=job['title']:raise ValueError('标题不一致')
  editor=page.locator('[contenteditable=true]')
  plain=await editor.evaluate('(e)=>{const n=e.cloneNode(true);n.querySelectorAll("a.zed-topic").forEach(a=>a.remove());return n.textContent}')
  norm=lambda s:re.sub(r'[\s\u200b]+','',s)
  if norm(plain)!=norm(job['body']):raise ValueError('简介回读与原稿不一致')
  topics=await editor.locator('a.zed-topic').all_text_contents()
  if {x.strip().lstrip('#').casefold() for x in topics}!={x.casefold() for x in job['tags']}:raise ValueError('话题实体不一致')
  if not await page.get_by_text('更改视频封面',exact=True).is_visible() or not state.get('coverSelected'):raise ValueError('封面未保存')
  if not await page.get_by_text('含 AI 生成内容',exact=True).is_visible():raise ValueError('AI声明未保存')
  if not await page.get_by_text('科技互联网',exact=True).is_visible():raise ValueError('领域未保存')
  if not await page.get_by_text('上传成功',exact=True).is_visible():raise ValueError('视频未上传成功')
  state.update(status='ready',topicsVerified=topics,message='发布前字段核对通过')
  if action=='submit':
   if (folder/'submit-attempt.json').exists():raise ValueError('已有提交动作，先核对回执')
   (folder/'submit-attempt.json').write_text(json.dumps({'title':job['title'],'status':'submitting'},ensure_ascii=False),encoding='utf-8')
   state['status']='submitting'
   await page.get_by_role('button',name='发布视频',exact=True).click()
   await page.wait_for_timeout(2200)
   text=await page.locator('body').inner_text()
   if '发布成功' in text or '成功发布' in text:state.update(status='submitted',message='平台提示发布成功',receiptUrl=page.url)
  return
 if action=='topic_existing_comfyui':
  import re
  await page.locator('.TopicSuggestion-TopicItem .topic-name').filter(has_text=re.compile(r'^#comfyUI$')).click();await page.keyboard.press('Escape')
  state['topicsVerified']=await page.locator('[contenteditable=true] a.zed-topic').all_text_contents();state['message']='发布字段已准备';return
 if action=='topics_finish':
  import re
  await page.locator('.TopicSuggestion-TopicItem .topic-name').filter(has_text=re.compile(r'^#AI绘画$')).click()
  await page.keyboard.press('ArrowRight');await page.keyboard.type(' #ComfyUI',delay=70)
  await page.locator('.TopicSuggestion-TopicItem .topic-name').filter(has_text=re.compile(r'^#ComfyUI$',re.I)).wait_for(state='visible')
  await page.locator('.TopicSuggestion-TopicItem .topic-name').filter(has_text=re.compile(r'^#ComfyUI$',re.I)).click();await page.keyboard.press('Escape')
  state['topicsVerified']=await page.locator('[contenteditable=true] a.zed-topic').all_text_contents();state['message']='标题、简介、话题、AI标记和领域已填写';return
 if action=='topic_more':
  import json
  await page.keyboard.press('ArrowRight');await page.keyboard.type(' #AI绘画',delay=70);await page.wait_for_timeout(700)
  data=await page.get_by_text('#AI绘画',exact=True).evaluate_all('(es)=>es.filter(e=>!e.closest("[contenteditable]")).map(e=>({html:e.outerHTML,parent:e.parentElement.outerHTML.slice(0,1800),grandparent:e.parentElement.parentElement.outerHTML.slice(0,2300)}))')
  (folder/'topic-options.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');return
 if action=='category_select':
  await page.get_by_text('科技互联网',exact=True).click();state['category']='科技互联网';return
 if action=='topic_open':
  editor=page.locator('[contenteditable=true]');await editor.click();await editor.press('Control+End')
  await page.keyboard.type(' #人工智能',delay=80);await page.wait_for_timeout(600);return
 if action=='topic_select':
  import json
  import re
  await page.locator('.TopicSuggestion-TopicItem .topic-name').filter(has_text=re.compile(r'^#人工智能$')).click()
  editor=page.locator('[contenteditable=true]')
  (folder/'topic-editor.json').write_text(json.dumps(await editor.evaluate('(e)=>e.outerHTML'),ensure_ascii=False),encoding='utf-8');return
 if action=='inspect_selects':
  import json
  data=await page.locator('select').evaluate_all('(es)=>es.map(e=>({class:e.className,value:e.value,options:[...e.options].map(o=>({value:o.value,label:o.textContent}))}))')
  (folder/'selects.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');return
 if action=='image_status':
  import json
  response=await page.wait_for_event('response',predicate=lambda r:'/images/' in r.url,timeout=8000)
  data=await response.json()
  safe={'keys':list(data),'status':data.get('status'),'state':data.get('state'),'width':data.get('width'),'height':data.get('height')}
  (folder/'image-processing.json').write_text(json.dumps(safe,ensure_ascii=False,indent=2),encoding='utf-8');state['imageProcessing']=safe;return
 if action=='fill':
  await page.get_by_placeholder('标题',exact=True).fill(job['title'])
  editor=page.locator('[contenteditable=true]')
  if await editor.count()!=1:raise ValueError('简介编辑器不唯一')
  await editor.fill(job['body']);state.update(status='editing',message='标题与简介已填写');return
 if action=='cover_open':
  await page.get_by_text('选择视频封面',exact=True).click();return
 if action=='cover_local':
  import json
  await page.get_by_text('本地上传',exact=True).click()
  data=await page.locator('input[type=file]').evaluate_all('(es)=>es.map(e=>({accept:e.accept,parent:e.parentElement.outerHTML.slice(0,2400)}))')
  (folder/'file-controls.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');return
 if action=='cover_upload':
  await page.locator('input[type=file][accept="image/png,image/jpeg,image/jpg"]').set_input_files(job['cover'])
  await page.wait_for_timeout(1000);return
 if action=='cover_confirm':
  import json
  from urllib.parse import urlsplit
  events=[]
  async def response(r):
   if 'image' in r.url or 'zvideo' in r.url:
    item={'path':urlsplit(r.url).path,'status':r.status}
    try:
     d=await r.json();err=d.get('error',{}) if isinstance(d,dict) else {};item['code']=err.get('code') if isinstance(err,dict) else None;item['message']=err.get('message') if isinstance(err,dict) else None
    except Exception:pass
    events.append(item);(folder/'cover-events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
  page.on('response',response)
  try:
   await page.get_by_role('button',name='确认选择',exact=True).click()
   await page.get_by_role('button',name='确认选择',exact=True).wait_for(state='hidden',timeout=20000)
   state['coverSelected']=True
  finally:page.remove_listener('response',response)
  return
 if action=='mark_open':
  await page.locator('button.VideoUploadForm-videoTypeSelectOverlay').click();return
 if action=='mark_select':
  await page.get_by_text('含 AI 生成内容',exact=True).click()
  await page.get_by_role('button',name='确认',exact=True).click();state['declaration']='含 AI 生成内容';return
 if action=='category_open':
  import json
  field=page.get_by_text('选择领域',exact=True)
  (folder/'category-control.json').write_text(json.dumps(await field.evaluate('(e)=>e.parentElement.outerHTML'),ensure_ascii=False),encoding='utf-8')
  try:await field.click(timeout=3000)
  except Exception as exc:
   (folder/'category-error.txt').write_text(str(exc),encoding='utf-8');raise
  return
 if action=='upload':
  import json
  if state.get('uploaded'):raise ValueError('已有上传，不能重复')
  field=page.locator('input[type=file][accept*=".mp4"]')
  if await field.count()!=1:raise ValueError('视频上传控件不唯一')
  state.update(status='uploading',uploaded=True,message='开始上传正式视频')
  (folder/'state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
  await field.set_input_files(job['video']);await page.wait_for_timeout(1800);return
 if action=='pages':
  state['pages']=[p.url.split('?')[0] for p in page.context.pages];return
 if action=='adopt_video_page':
  candidates=[p for p in page.context.pages if p!=page and p.url.split('?')[0]=='https://www.zhihu.com/upload-video']
  if len(candidates)!=1:raise ValueError('视频新页面数量：'+str(len(candidates)))
  target=candidates[0];url=target.url
  state['openedVideoPage']=url.split('?')[0]
  await page.goto(url,wait_until='domcontentloaded');await page.wait_for_timeout(1800);await target.close()
  return
 if action=='open':
  entry=page.get_by_text('发视频',exact=True).filter(visible=True)
  if await entry.count()!=1:raise ValueError('发视频入口不唯一')
  href=await entry.evaluate('(e)=>e.closest("a")?.href')
  if href:await page.goto(href,wait_until='domcontentloaded')
  else:await entry.click()
  await page.wait_for_timeout(1800)
  state.update(status='ready_to_upload',message='已打开视频发布页')
 else:raise ValueError('先核对当前知乎页面')
