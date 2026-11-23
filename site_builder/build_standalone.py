import re,json,glob,os
src=open('project/Main.dc.html').read()
charts=json.load(open('charts.json'))
names=sorted(os.path.basename(f) for f in glob.glob('img/*.jpg'))
# map blob urls to relative image files (charts are in order 1..18)
for i,c in enumerate(charts): src=src.replace(c['url'],'img/'+names[i])
hs=src.index('<helmet>'); he=src.index('</helmet>')
helmet=src[hs+8:he]
body=src[he+9:src.index('</x-dc>')]
js=src[src.index('data-dc-script'):]; js=js[js.index('>')+1:js.index('</script>')]
body=body.replace('<sc-for ','<template data-k="for" ').replace('</sc-for>','</template>').replace('<sc-if ','<template data-k="if" ').replace('</sc-if>','</template>')
runtime=r'''
class DCLogic{constructor(p){this.props=p||{};this.state={}}
 setState(o){Object.assign(this.state,typeof o==='function'?o(this.state):o);schedule()}}
'''+js+r'''
const TPL=document.getElementById('tpl');
const APP=document.getElementById('app');
const inst=new Component({});
function look(scope,path){path=path.trim();let v=scope;for(const k of path.split('.')){if(v==null)return undefined;v=v[k]}return v}
function fill(str,scope){return str.replace(/\{\{([^}]*)\}\}/g,(m,p)=>{const v=look(scope,p);return v==null?'':String(v)})}
function isHole(s){return /^\s*\{\{[^}]*\}\}\s*$/.test(s)}
function renderNodes(nodes,scope,parent){for(const n of nodes)renderNode(n,scope,parent)}
function renderNode(n,scope,parent){
 if(n.nodeType===3){const t=n.textContent;parent.appendChild(document.createTextNode(t.indexOf('{{')>=0?fill(t,scope):t));return}
 if(n.nodeType!==1)return;
 if(n.tagName==='TEMPLATE'&&n.dataset.k){
  const kids=n.content.childNodes;
  if(n.dataset.k==='for'){const list=look(scope,n.getAttribute('list').replace(/[{}]/g,''))||[];const as=n.getAttribute('as');
   for(const it of list){const s=Object.assign(Object.create(scope),{[as]:it});renderNodes(kids,s,parent)}}
  else{const v=look(scope,n.getAttribute('value').replace(/[{}]/g,''));if(v)renderNodes(kids,scope,parent)}
  return}
 const el=document.createElement(n.tagName.toLowerCase());let val=null;
 for(const a of n.attributes){const name=a.name;
  if(name.startsWith('hint-'))continue;
  if(/^on(click|input|change)$/.test(name)){const f=look(scope,a.value.replace(/[{}]/g,''));if(typeof f==='function')el.addEventListener(name.slice(2),f);continue}
  const v=a.value.indexOf('{{')>=0?fill(a.value,scope):a.value;
  if(name==='value'){val=v;continue}
  el.setAttribute(name,v)}
 renderNodes(n.childNodes,scope,el);
 if(val!==null)el.value=val;
 parent.appendChild(el)}
let pending=false;
function schedule(){if(pending)return;pending=true;requestAnimationFrame(()=>{pending=false;render()})}
function render(){
 const ae=document.activeElement;const id=ae&&ae.id;const ss=ae&&ae.selectionStart,se=ae&&ae.selectionEnd;const y=window.scrollY;
 const vals=inst.renderVals();const frag=document.createDocumentFragment();
 renderNodes(TPL.content.childNodes,vals,frag);APP.replaceChildren(frag);
 if(id){const e=document.getElementById(id);if(e){e.focus();try{if(ss!=null)e.setSelectionRange(ss,se)}catch(x){}}}
 window.scrollTo(0,y)}
render();
'''
html=f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Recovery Lab</title>
{helmet}
</head>
<body>
<div id="app"></div>
<template id="tpl">{body}</template>
<script>
{runtime}
</script>
</body>
</html>'''
os.makedirs('standalone',exist_ok=True)
open('standalone/index.html','w').write(html)
os.system('rm -rf standalone/img && cp -r img standalone/img')
print(len(html))
