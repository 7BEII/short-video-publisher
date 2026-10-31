import asyncio,json,re

async def apply(page,app,state,command,folder):
 if command=='login_qr':
  diagnostics=[]
  for frame in page.frames:
   diagnostics.append({'url':frame.url.split('?')[0],'images':await frame.locator('img').evaluate_all('(es)=>es.map(e=>({class:e.className,alt:e.alt,width:e.width,height:e.height,visible:!!e.getClientRects().length}))')})
   qr=frame.locator('img.js_qrcode_img').filter(visible=True)
   if await qr.count() and await qr.first.is_visible():
    await qr.first.screenshot(path=str(folder/'login-qr.png'))
    state.update(status='waiting_scan',message='请微信扫码登录视频号助手');return
  (folder/'qr-controls.json').write_text(json.dumps(diagnostics,ensure_ascii=False,indent=2),encoding='utf-8')
  raise ValueError('当前页面未显示登录二维码')
 elif command=='prepare':
  if state.get('uploaded'):raise ValueError('已有上传稿件，不重复上传')
  if '/login' in page.url:raise ValueError('视频号尚未登录')
  await app.upload_video_file(page,app.file_path)
  state.update(uploaded=True,status='uploading')
  target=page
  if not await target.locator('div.input-editor').count():
   target=next(frame for frame in page.frames if '/micro/content/post/create' in frame.url)
  await target.locator('div.input-editor').wait_for(state='visible',timeout=180000)
  await target.locator('div.input-editor').fill(app.desc)
  await app.set_short_title(target,app.title,app.short_title)
  state['status']='editing'
 elif command=='covers':
  raise ValueError('请分别执行横竖封面步骤，禁止上游跳过失败后继续')
 elif command=='cover_vertical_open':
  await page.locator('.vertical-cover-wrap').click()
  direct=page.get_by_text('直接编辑',exact=True).filter(visible=True)
  if await direct.count():await direct.click()
 elif command=='cover_vertical_upload':
  dialog=page.locator('div.weui-desktop-dialog').filter(has_text='编辑个人主页卡片').filter(visible=True)
  if await dialog.count()!=1:raise ValueError('竖封面弹窗不唯一')
  await app.upload_thumbnail_in_dialog(page,dialog,app.thumbnail_portrait_path)
 elif command=='cover_horizontal_open':
  await page.locator('.horizon-cover-wrap').click()
 elif command=='cover_horizontal_edit':
  await page.get_by_text('直接编辑',exact=True).click()
 elif command=='cover_horizontal_upload':
  dialog=page.locator('div.weui-desktop-dialog').filter(has_text='编辑分享卡片').filter(visible=True)
  if await dialog.count()!=1:raise ValueError('当前封面弹窗不唯一')
  await app.upload_thumbnail_in_dialog(page,dialog,app.thumbnail_landscape_path)
 elif command=='metadata':
  await app.set_short_title(page,app.title,app.short_title)
  editor=page.locator('div.input-editor')
  await editor.click();await editor.press('Control+End');await page.keyboard.press('Enter')
  if app.tags:await page.keyboard.type('#'+app.tags[0],delay=80)
  await page.wait_for_timeout(1200)
 elif command=='declaration_open':
  await page.get_by_text('选择视频标注',exact=True).click()
 elif command=='declaration_select':
  if state.get('declarationTarget')!='none':await page.get_by_text(state['declarationTarget'],exact=True).filter(visible=True).click()
 elif command=='verify' or command=='submit':
  editor=page.locator('div.input-editor')
  actual=[x.strip().lstrip('#') for x in await editor.locator('[data-type="topic"]').all_text_contents()]
  if set(actual)!=set(app.tags) or len(actual)!=len(app.tags):raise ValueError('话题实体不一致')
  plain=await editor.evaluate('(e)=>{const c=e.cloneNode(true);c.querySelectorAll("[data-type=topic]").forEach(n=>n.remove());return c.textContent}')
  if re.sub(r'\s+','',plain)!=re.sub(r'\s+','',app.desc):raise ValueError('正文不一致')
  if await page.get_by_text('标题包含特殊字符',exact=False).filter(visible=True).count():raise ValueError('短标题含不允许字符')
  if state.get('declarationTarget')!='none' and not await page.get_by_text(state['declarationTarget'],exact=True).filter(visible=True).count():raise ValueError('标注未保存')
  covers=[]
  for selector in ('.vertical-cover-wrap','.horizon-cover-wrap'):
   images=await page.locator(selector+' img').evaluate_all('(es)=>es.filter(i=>i.complete&&i.naturalWidth>0).map(i=>i.src.split("?")[0])')
   if not images:raise ValueError('缺少封面预览：'+selector)
   covers.append(images)
  state.update(topicsVerified=actual,coversVerified=['3:4','4:3'],declaration=state.get('declarationTarget'),shortTitle=app.short_title,status='ready',message='字段核对完成')
  if command=='submit':
   if state.get('submitted'):raise ValueError('已提交，不重复发表')
   button=page.get_by_role('button',name='发表',exact=True).filter(visible=True)
   if await button.count()!=1 or not await button.is_enabled():raise ValueError('发表按钮不可用')
   state['status']='submitting'
   (folder/'state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
   await button.click()
   await page.wait_for_function("() => location.pathname.includes('/post/list') || document.body.innerText.includes('发表成功')",timeout=45000)
   await page.wait_for_timeout(2000)
   text=await page.locator('body').last.inner_text()
   if '发表成功' not in text and app.short_title not in text and app.desc[:20] not in text:raise ValueError('发表后未核对到作品')
   state.update(status='submitted',submitted=True,message='视频号作品列表已核对本次视频',receiptUrl=page.url)
 elif command=='topics':
  editor=page.locator('div.input-editor');await editor.click();await editor.press('Control+End')
  for tag in app.tags[1:]:
   await page.keyboard.type(' #'+tag,delay=65);await page.keyboard.press('Space')
  actual=await editor.locator('[data-type="topic"]').all_text_contents()
  if set(x.strip().lstrip('#') for x in actual)!=set(app.tags):raise ValueError('实际话题实体不一致：'+str(actual))
  state['topicsVerified']=actual
 elif command=='inspect_controls':
  details=await page.locator('input[type=file],[class*="cover"],[role=dialog],.weui-desktop-dialog').evaluate_all('(es)=>es.map(e=>({tag:e.tagName,accept:e.accept,html:e.outerHTML.slice(0,8000)}))')
  (folder/'controls.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
  (folder/'cover-entry.json').write_text(json.dumps(await page.get_by_text('分享卡片',exact=True).evaluate_all('(es)=>es.map(e=>({parents:[e.parentElement,e.parentElement.parentElement,e.parentElement.parentElement.parentElement].map(p=>({class:p.className,text:p.innerText}))}))'),ensure_ascii=False,indent=2),encoding='utf-8')
 else:raise ValueError('未实现的受控步骤：'+command)
 (folder/'form.json').write_text(json.dumps({'text':await page.locator('body').last.inner_text(),'editor':await page.locator('div.input-editor').evaluate_all('(es)=>es.map(e=>e.outerHTML)')},ensure_ascii=False,indent=2),encoding='utf-8')
