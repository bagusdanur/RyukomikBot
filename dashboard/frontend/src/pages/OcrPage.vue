<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import { getCsrfToken } from "../api";

interface Job { id:string; status:string; stage:string; progress:number; review_count:number; queue_position?:number; review_pages?:Array<{page:number;count:number}>; error?:string|null; created_at:number; options?:{original_filename?:string;input_files?:string[];comic_title?:string;chapter?:string;title_slug?:string;comic_id?:string;chapter_id?:string} }
interface Status { memory:{available:number}; worker:{status:string}; queue:Record<string,number> }
interface ComicImage { id:string; filename:string; width:number; height:number; status:string; region_count:number; crop_top?:number; crop_bottom?:number }
interface Box { x:number; y:number; width:number; height:number }
interface Region { id:string; source_text:string; translation:string; bbox:Box; status:string; metadata:Record<string,unknown> }
interface ComicFolder { id:string; title:string; slug:string; category?:string; chapter_count:number; job_count:number }
interface ChapterFolder { id:string; comic_id:string; number:string; slug:string; job_count:number }
interface MemoryJob { id:string;chapter_number:string;status:string;stage:string;progress:number;error?:string|null;proposal?:Record<string,any>|null }
interface MemoryState { profile:Record<string,any>;references:Array<{id:string;chapter_number:string;summary:Record<string,any>}>;jobs:MemoryJob[] }
interface RawResult { id:string;title:string;source:string;source_name:string;image?:string;latest_chapter?:string }
interface RawChapter { id:string;title:string;date?:string }
interface RawPackage { count:number;pages:Array<{page:number;width:number;height:number}>;min_height:number;max_height:number;bytes:number;height_limit?:number;source_boundary_cuts?:number;unsafe_cuts?:number }
interface PreparedRaw { token:string;state:string;original?:RawPackage;joined?:RawPackage;error?:string }
interface SettingRow { key:string;value:string }

const files=ref<File[]>([]), minY=ref(0), uploading=ref(false), progress=ref(0), error=ref("");
const comics=ref<ComicFolder[]>([]), chapters=ref<ChapterFolder[]>([]), selectedComic=ref<ComicFolder|null>(null), selectedChapter=ref<ChapterFolder|null>(null);
const newComicTitle=ref(""), newComicCategory=ref<"manga"|"manhwa"|"manhua">("manhwa"), newChapterNumber=ref(""), creatingFolder=ref(false), deleting=ref("");
const memoryMode=ref<"indonesian_only"|"paired">("indonesian_only");
const memoryOpen=ref(false), memoryState=ref<MemoryState|null>(null), memoryChapter=ref(""), rawZip=ref<File|null>(null), translatedZip=ref<File|null>(null), memoryUploading=ref(false), memoryProgress=ref(0), memoryDrafts=ref<Record<string,string>>({}), memoryError=ref("");
const jobs=ref<Job[]>([]), system=ref<Status|null>(null), input=ref<HTMLInputElement|null>(null), drag=ref(false);
const aiSettingsOpen=ref(false),aiModel=ref(""),aiFallbacks=ref(""),aiSaving=ref(false),aiTesting=ref(false),aiMessage=ref("");
const rawQuery=ref(""),rawResults=ref<RawResult[]>([]),rawSource=ref(""),rawMangaId=ref(""),rawChapters=ref<RawChapter[]>([]),rawChapterId=ref(""),rawSearching=ref(false),rawLoadingChapters=ref(false),rawAction=ref<""|"download"|"import">("");
const rawImportOpen=ref(false);
const rawDownloadOpen=ref(false),rawPreparing=ref(false),rawDownloadMode=ref<"original"|"joined">("original"),rawPreview=ref<PreparedRaw|null>(null),rawPrepareError=ref("");
let rawPollTimer:number|undefined,rawPrepareSequence=0;
const rawChosenPackage=computed(()=>rawPreview.value?.[rawDownloadMode.value]);
function resetRawDownload(){rawImportOpen.value=false;rawPrepareSequence++;if(rawPollTimer)clearTimeout(rawPollTimer);rawPreparing.value=false;rawDownloadOpen.value=false;rawPreview.value=null;rawPrepareError.value=""}
watch([rawSource,rawMangaId,rawChapterId],resetRawDownload);
async function pollRaw(token:string,sequence:number){
  try{const state=await api<PreparedRaw>(`/api/tools/translator/raw/prepared/${encodeURIComponent(token)}`);if(sequence!==rawPrepareSequence)return;rawPreview.value=state;
    if(state.state==="READY"||state.state==="FAILED"){rawPreparing.value=false;rawPrepareError.value=state.error||"";return}
    rawPollTimer=window.setTimeout(()=>{void pollRaw(token,sequence)},2000);
  }catch(e){if(sequence!==rawPrepareSequence)return;rawPreparing.value=false;rawPrepareError.value=e instanceof Error?e.message:"Gagal memeriksa paket RAW."}
}
function chooseRawMode(mode:"original"|"joined"){
  // Di HP, radio kecil di dalam kartu sering tidak kena tap. Seluruh kartu
  // sekarang memilih format, dan kalau paket format itu belum siap kita
  // langsung menyiapkannya supaya tombol unduh tidak "mati" tanpa penjelasan.
  rawDownloadMode.value=mode;
  if(!rawPreview.value?.[mode]&&!rawPreparing.value&&rawChapterId.value&&!rawAction.value)void prepareRawPreview(false);
}
function openRawDownload(){void prepareRawPreview(false)}
async function prepareRawPreview(forImport=false){
  if(!rawChapterId.value||rawAction.value||rawPreparing.value)return;if(!forImport)rawDownloadOpen.value=true;rawPreparing.value=true;rawPrepareError.value="";const sequence=++rawPrepareSequence;
  try{const state=await api<PreparedRaw>("/api/tools/translator/raw/prepare",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(rawPayload())});if(sequence!==rawPrepareSequence)return;rawPreview.value=state;await pollRaw(state.token,sequence)}
  catch(e){if(sequence!==rawPrepareSequence)return;rawPreparing.value=false;rawPrepareError.value=e instanceof Error?e.message:"Gagal menyiapkan RAW."}
}
const reviewJob=ref<Job|null>(null), images=ref<ComicImage[]>([]), currentImage=ref<ComicImage|null>(null);
const regions=ref<Region[]>([]), selected=ref<Region|null>(null), rendering=ref(false), previewKey=ref(Date.now());
// Webtoon mode stacks every page full-width in one continuous scroll, like
// reading the source on a webtoon site. Page mode keeps the original
// single-page editor with the side panel. The choice is remembered per admin.
const webtoon=ref(localStorage.getItem("ocrReviewWebtoon")==="1");
const webtoonPages=computed(()=>webtoon.value?[...images.value].sort((a,b)=>a.filename.localeCompare(b.filename,undefined,{numeric:true})):[]);
function setWebtoon(value:boolean){webtoon.value=value;localStorage.setItem("ocrReviewWebtoon",value?"1":"0")}
// Immersive reader: the app shell keeps a fixed 254px sidebar and a content
// gutter, which crop the comic strip. Fullscreen renders the reader as its own
// fixed overlay above the shell so the artwork gets the whole viewport.
const immersive=ref(false);
function setImmersive(value:boolean){
  immersive.value=value&&webtoon.value;
  document.documentElement.style.overflow=immersive.value?"hidden":"";
  // Entering the reader always starts at the top; the ambient page scroll
  // position has no meaning inside the fixed overlay.
  if(immersive.value)requestAnimationFrame(()=>{const el=document.getElementById("wt-full-scroll");if(el)el.scrollTop=0});
}
// Leaving webtoon or closing the review must never strand the page in a
// scroll-locked fullscreen overlay.
watch([webtoon,()=>reviewJob.value],()=>{if(!webtoon.value||!reviewJob.value)setImmersive(false)});
function jumpToPage(image:ComicImage){if(!webtoon.value)return chooseImage(image);const target=document.getElementById(`wt-scroll-${image.id}`)||document.getElementById(`wt-${image.id}`);target?.scrollIntoView({behavior:"smooth",block:"start"})}
// Reader position badge: report which page is currently on screen while the
// immersive strip scrolls, so a long chapter is not a blind scroll.
const wtScrollEl=ref<HTMLElement|null>(null);
const wtCounterEl=ref<HTMLElement|null>(null);
function onWtScroll(){
  const scroller=wtScrollEl.value;
  if(!scroller)return;
  const top=scroller.getBoundingClientRect().top;
  const pages=[...scroller.querySelectorAll<HTMLElement>(".wt-full-page")];
  if(!pages.length)return;
  let index=0;
  for(let i=0;i<pages.length;i++){if(pages[i].getBoundingClientRect().top-top<=8)index=i}
  if(wtCounterEl.value)wtCounterEl.value.textContent=`${index+1} / ${pages.length}`;
}
const edit=ref({translation:"",x:0,y:0,width:10,height:10,fontSize:20,alignment:"center",lineSpacing:0.12});
let timer:number|undefined;

const queueJobs=ref<Job[]>([]);
const active=computed(()=>queueJobs.value.length);
const runningJob=computed(()=>queueJobs.value.find(job=>job.status==="PROCESSING"));
const queueMessage=ref("");
const queueError=ref("");
let refreshSequence=0;
// The running job is pinned first; everything waiting follows the manual order
// set with the arrows (falling back to created_at for rows the worker has not
// renumbered yet), which is exactly the order the worker will claim them in.
const globalQueue=computed(()=>queueJobs.value);
const movableQueue=computed(()=>globalQueue.value.filter(job=>job.status!=="PROCESSING"));
const movableIndex=(job:Job)=>movableQueue.value.findIndex(item=>item.id===job.id);
const queueBusy=ref("");
async function moveJob(job:Job,move:"up"|"down"|"top"){
  if(job.status==="PROCESSING"||queueBusy.value)return;
  queueBusy.value=job.id;queueMessage.value="";queueError.value="";
  ++refreshSequence;
  try{
    const result=await api<{queue:Array<{id:string;position:number}>}>(`/api/tools/translator/jobs/${job.id}/queue`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({move})});
    const positions=new Map(result.queue.map(entry=>[entry.id,entry.position]));
    queueJobs.value=queueJobs.value.map(entry=>positions.has(entry.id)?{...entry,queue_position:positions.get(entry.id)}:entry).sort((a,b)=>{
      if(a.status==="PROCESSING")return -1;
      if(b.status==="PROCESSING")return 1;
      return (a.queue_position??a.created_at)-(b.queue_position??b.created_at)||a.created_at-b.created_at||a.id.localeCompare(b.id);
    });
    queueMessage.value=`Urutan ${name(job)} tersimpan. Berlaku setelah job yang berjalan selesai.`;
    await refresh(true);
  }catch(e){queueError.value=e instanceof Error?e.message:"Gagal mengatur urutan antrean."}
  finally{queueBusy.value=""}
}
const rawSources=computed(()=>Array.from(new Map(rawResults.value.map(item=>[item.source,item.source_name])).entries()).map(([id,name])=>({id,name})));
const rawTitles=computed(()=>rawResults.value.filter(item=>item.source===rawSource.value));
const selectedRawTitle=computed(()=>rawTitles.value.find(item=>item.id===rawMangaId.value)||null);
const selectedChapterJobs=computed(()=>{if(!selectedComic.value||!selectedChapter.value)return[];return jobs.value.filter(job=>job.options?.chapter_id===selectedChapter.value?.id||(job.options?.comic_title===selectedComic.value?.title&&job.options?.chapter===selectedChapter.value?.number))});
const ram=computed(()=>system.value?(system.value.memory.available/1024**3).toFixed(1):"-");
const headers=():Record<string,string>=>{const token=getCsrfToken();return token?{"X-CSRF-Token":token}:{}};
async function api<T>(url:string,init:RequestInit={}):Promise<T>{const r=await fetch(url,{credentials:"same-origin",cache:"no-store",...init,headers:{...headers(),...Object.fromEntries(new Headers(init.headers).entries())}});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||d.error||`Error ${r.status}`);return d}
async function loadAiSettings(){const rows=await api<SettingRow[]>("/api/tools/translator/settings");const values=Object.fromEntries(rows.map(row=>[row.key,row.value]));aiModel.value=values.ninerouter_model||"ag/gemini-3.8-flash-low";aiFallbacks.value=values.ninerouter_fallback_models||"ag/claude-sonnet-4-6,glm/GLM-5.3-Flash"}
async function openAiSettings(){aiSettingsOpen.value=true;aiMessage.value="";try{await loadAiSettings()}catch(e){aiMessage.value=e instanceof Error?e.message:"Gagal memuat pengaturan."}}
async function saveAiSettings(){if(!aiModel.value.trim()||aiSaving.value)return;aiSaving.value=true;aiMessage.value="";try{await api("/api/tools/translator/settings",{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({ninerouter_model:aiModel.value.trim(),ninerouter_fallback_models:aiFallbacks.value.trim()})});aiMessage.value="Tersimpan. Model dipakai untuk job berikutnya."}catch(e){aiMessage.value=e instanceof Error?e.message:"Gagal menyimpan."}finally{aiSaving.value=false}}
async function testAiModel(){if(!aiModel.value.trim()||aiTesting.value)return;aiTesting.value=true;aiMessage.value="";try{await api("/api/tools/translator/settings/test-translator",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({model:aiModel.value.trim()})});aiMessage.value=`Koneksi ${aiModel.value.trim()} berhasil.`}catch(e){aiMessage.value=e instanceof Error?e.message:"Tes model gagal."}finally{aiTesting.value=false}}
function select(values?:FileList|null){if(!values)return;const incoming=Array.from(values);if(files.value.length+incoming.length>60){error.value="Maksimal 60 gambar per job.";return}for(const value of incoming){if(!/\.(png|jpe?g|webp|zip)$/i.test(value.name)){error.value="Format harus PNG, JPG, WEBP, atau ZIP.";return}const limit=/\.zip$/i.test(value.name)?100:25;if(value.size>limit*1024*1024){error.value=`${value.name} melebihi ${limit} MB.`;return}}const combined=[...files.value,...incoming];if(combined.reduce((sum,item)=>sum+item.size,0)>100*1024*1024){error.value="Total upload maksimal 100 MB.";return}files.value=combined;error.value=""}
function picked(e:Event){const el=e.target as HTMLInputElement;select(el.files);el.value=""}
function dropped(e:DragEvent){e.preventDefault();drag.value=false;select(e.dataTransfer?.files)}
async function refresh(force=false){
  if(queueBusy.value&&!force)return;
  const sequence=++refreshSequence;
  try{
    const [nextJobs,nextSystem,nextComics,nextQueue]=await Promise.all([api<Job[]>("/api/tools/translator/jobs?limit=20"),api<Status>("/api/tools/translator/status"),api<ComicFolder[]>("/api/tools/translator/comics"),api<Job[]>("/api/tools/translator/queue")]);
    if(sequence!==refreshSequence)return;
    jobs.value=nextJobs;system.value=nextSystem;comics.value=nextComics;queueJobs.value=nextQueue;
    if(selectedComic.value){selectedComic.value=comics.value.find(item=>item.id===selectedComic.value?.id)||null;if(selectedComic.value)await loadChapters(selectedComic.value,false)}
    error.value="";
  }catch(e){if(sequence===refreshSequence)error.value=e instanceof Error?e.message:"Service translator tidak tersedia."}
}
async function loadChapters(comic:ComicFolder,reset=true){selectedComic.value=comic;chapters.value=await api<ChapterFolder[]>(`/api/tools/translator/comics/${comic.id}/chapters`);if(reset)selectedChapter.value=null;else if(selectedChapter.value)selectedChapter.value=chapters.value.find(item=>item.id===selectedChapter.value?.id)||null}
async function loadMemory(open=false){if(!selectedComic.value)return;memoryState.value=await api<MemoryState>(`/api/tools/translator/comics/${selectedComic.value.id}/memory`);if(open)memoryOpen.value=true;for(const item of memoryState.value.jobs){if(item.status==="WAITING_APPROVAL"&&item.proposal&&memoryDrafts.value[item.id]===undefined)memoryDrafts.value[item.id]=JSON.stringify(item.proposal,null,2)}}
async function uploadMemory(){if(!selectedComic.value||(memoryMode.value==="paired"&&!rawZip.value)||!translatedZip.value||!memoryChapter.value.trim()||memoryUploading.value)return;memoryUploading.value=true;memoryProgress.value=0;memoryError.value="";const form=new FormData();form.append("chapterNumber",memoryChapter.value.trim());form.append("referenceMode",memoryMode.value);if(memoryMode.value==="paired"&&rawZip.value)form.append("rawZip",rawZip.value);form.append("translatedZip",translatedZip.value);try{await new Promise<void>((ok,fail)=>{const x=new XMLHttpRequest();x.open("POST",`/api/tools/translator/comics/${selectedComic.value!.id}/memory/analyze`);const token=getCsrfToken();if(token)x.setRequestHeader("X-CSRF-Token",token);x.upload.onprogress=e=>{if(e.lengthComputable)memoryProgress.value=Math.round(e.loaded/e.total*100)};x.onload=()=>{const d=JSON.parse(x.responseText||"{}");x.status>=200&&x.status<300?ok():fail(new Error(d.detail||d.error||`Error ${x.status}`))};x.onerror=()=>fail(new Error("Upload bahan belajar gagal."));x.send(form)});rawZip.value=null;translatedZip.value=null;await loadMemory()}catch(e){memoryError.value=e instanceof Error?e.message:"Analisis gagal dibuat."}finally{memoryUploading.value=false}}
async function approveMemory(job:MemoryJob){if(!selectedComic.value)return;try{const proposal=JSON.parse(memoryDrafts.value[job.id]||JSON.stringify(job.proposal));await api(`/api/tools/translator/comics/${selectedComic.value.id}/memory/jobs/${job.id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({proposal})});await api(`/api/tools/translator/comics/${selectedComic.value.id}/memory/jobs/${job.id}/approve`,{method:"POST"});await loadMemory()}catch(e){error.value=e instanceof Error?e.message:"Gagal menyimpan memory."}}
async function cancelMemory(job:MemoryJob){if(!selectedComic.value)return;await api(`/api/tools/translator/comics/${selectedComic.value.id}/memory/jobs/${job.id}/cancel`,{method:"POST"});await loadMemory()}
async function deleteReference(id:string){if(!selectedComic.value||!window.confirm("Hapus bahan referensi ini? Memory yang sudah disetujui tetap tersimpan."))return;await api(`/api/tools/translator/comics/${selectedComic.value.id}/memory/references/${id}`,{method:"DELETE"});await loadMemory()}
async function createComic(){const title=newComicTitle.value.trim();if(!title||creatingFolder.value)return;creatingFolder.value=true;try{const comic=await api<ComicFolder>("/api/tools/translator/comics",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title,category:newComicCategory.value})});newComicTitle.value="";await refresh();await loadChapters(comic)}catch(e){error.value=e instanceof Error?e.message:"Gagal membuat folder komik."}finally{creatingFolder.value=false}}
async function renameComic(){if(!selectedComic.value||creatingFolder.value)return;const value=window.prompt("Nama judul/folder komik baru",selectedComic.value.title);if(value===null)return;const title=value.trim();if(!title||title===selectedComic.value.title)return;creatingFolder.value=true;try{const comic=await api<ComicFolder>(`/api/tools/translator/comics/${selectedComic.value.id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({title})});selectedComic.value=comic;await refresh()}catch(e){error.value=e instanceof Error?e.message:"Gagal mengganti nama folder komik."}finally{creatingFolder.value=false}}
async function createChapter(){const number=newChapterNumber.value.trim();if(!number||!selectedComic.value||creatingFolder.value)return;creatingFolder.value=true;try{const item=await api<ChapterFolder>(`/api/tools/translator/comics/${selectedComic.value.id}/chapters`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({number})});newChapterNumber.value="";await loadChapters(selectedComic.value);selectedChapter.value=item}catch(e){error.value=e instanceof Error?e.message:"Gagal membuat folder chapter."}finally{creatingFolder.value=false}}
function openChapter(item:ChapterFolder){selectedChapter.value=item;files.value=[];error.value=""}
async function openJobFolder(job:Job){const comic=comics.value.find(item=>item.id===job.options?.comic_id)||comics.value.find(item=>item.title===job.options?.comic_title);if(!comic)return;await loadChapters(comic);selectedChapter.value=chapters.value.find(item=>item.id===job.options?.chapter_id)||chapters.value.find(item=>item.number===job.options?.chapter)||null;window.scrollTo({top:0,behavior:"smooth"})}
async function searchRaw(){const query=rawQuery.value.trim();if(query.length<2||rawSearching.value)return;rawSearching.value=true;error.value="";try{rawResults.value=await api<RawResult[]>(`/api/raw/search?q=${encodeURIComponent(query)}&source=all`);rawSource.value=rawSources.value[0]?.id||"";rawMangaId.value="";rawChapters.value=[];rawChapterId.value="";if(!rawResults.value.length)error.value="Judul tidak ditemukan pada source RAW yang aktif."}catch(e){error.value=e instanceof Error?e.message:"Pencarian RAW gagal."}finally{rawSearching.value=false}}
function changeRawSource(){rawMangaId.value="";rawChapters.value=[];rawChapterId.value=""}
async function loadRawChapters(){rawChapters.value=[];rawChapterId.value="";if(!rawSource.value||!rawMangaId.value)return;rawLoadingChapters.value=true;error.value="";try{rawChapters.value=await api<RawChapter[]>(`/api/tools/translator/raw/${encodeURIComponent(rawSource.value)}/${encodeURIComponent(rawMangaId.value)}/chapters`);rawChapterId.value=rawChapters.value[0]?.id||"";if(!rawChapters.value.length)error.value="Source ini tidak mengembalikan daftar chapter."}catch(e){error.value=e instanceof Error?e.message:"Daftar chapter gagal dimuat."}finally{rawLoadingChapters.value=false}}
function rawPayload(){return{source:rawSource.value,manga_id:rawMangaId.value,chapter_id:rawChapterId.value,comic_id:selectedComic.value?.id,target_chapter_id:selectedChapter.value?.id,title:selectedComic.value?.title,chapter:selectedChapter.value?.number,min_y:Math.max(0,minY.value||0),...(rawDownloadOpen.value&&rawPreview.value?.token&&rawChosenPackage.value?{prepared_token:rawPreview.value.token,raw_mode:rawDownloadMode.value}:{})}}
function openRawImport(){if(!selectedComic.value||!selectedChapter.value||!rawChapterId.value||rawAction.value)return;rawImportOpen.value=true;error.value="";void prepareRawPreview(true)}
async function importRaw(){
  if(!selectedComic.value||!selectedChapter.value||!rawChapterId.value||rawAction.value)return;
  const mode=rawDownloadMode.value,payload=rawPayload(),sequence=++rawPrepareSequence;
  if(rawPollTimer)clearTimeout(rawPollTimer);
  rawAction.value="import";rawDownloadOpen.value=true;rawPreparing.value=true;error.value="";rawPrepareError.value="";
  try{
    let state=rawPreview.value;
    if(!state?.[mode])state=await api<PreparedRaw>("/api/tools/translator/raw/prepare",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    const deadline=Date.now()+15*60*1000;
    while(!state?.[mode]){
      if(sequence!==rawPrepareSequence)throw new Error("Pilihan RAW berubah. Mulai kembali pada chapter yang dipilih.");
      rawPreview.value=state;
      if(state?.state==="FAILED")throw new Error(state.error||"Persiapan RAW gagal.");
      if(!state?.token||Date.now()>deadline)throw new Error("Persiapan RAW terlalu lama. Coba lagi.");
      await new Promise(resolve=>window.setTimeout(resolve,2000));
      state=await api<PreparedRaw>(`/api/tools/translator/raw/prepared/${encodeURIComponent(state.token)}`);
    }
    if(sequence!==rawPrepareSequence)throw new Error("Pilihan RAW berubah. Mulai kembali pada chapter yang dipilih.");
    rawPreview.value=state;rawPreparing.value=false;
    await api("/api/tools/translator/raw/import",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...payload,prepared_token:state.token,raw_mode:mode})});
    rawImportOpen.value=false;await refresh();
  }catch(e){error.value=e instanceof Error?e.message:"Download dan import RAW gagal."}
  finally{rawAction.value="";rawPreparing.value=false}
}

async function downloadRaw(){if(!rawPreview.value?.token||!rawChosenPackage.value||rawAction.value)return;rawAction.value="download";error.value="";try{const response=await fetch("/api/tools/translator/raw/download",{method:"POST",credentials:"same-origin",headers:{...headers(),"Content-Type":"application/json"},body:JSON.stringify({...rawPayload(),prepared_token:rawPreview.value.token,raw_mode:rawDownloadMode.value})});if(!response.ok){const detail=await response.json().catch(()=>({}));throw new Error(detail.detail||`Error ${response.status}`)}const blob=await response.blob();const disposition=response.headers.get("content-disposition")||"";const matched=disposition.match(/filename\*?=(?:UTF-8''|\")?([^";]+)/i);const filename=decodeURIComponent((matched?.[1]||`${rawSource.value}-${rawChapterId.value}.zip`).replace(/"$/,""));const url=URL.createObjectURL(blob);const anchor=document.createElement("a");anchor.href=url;anchor.download=filename;anchor.click();URL.revokeObjectURL(url)}catch(e){error.value=e instanceof Error?e.message:"Download RAW gagal."}finally{rawAction.value=""}}
// Clean-only: komik yang SUDAH diterjemahkan cukup dibersihkan logo scanlator-nya
// lalu ditempeli branding Ryukomik. Tidak ada OCR translasi maupun typeset.
const cleanOpen=ref(false),cleanFiles=ref<File[]>([]),cleanErase=ref(false),cleanTitle=ref(""),cleanUploading=ref(false),cleanProgress=ref(0),cleanError=ref("");
function pickClean(event:Event){const input=event.target as HTMLInputElement;cleanFiles.value=Array.from(input.files||[])}
async function submitClean(){
  if(!cleanFiles.value.length||cleanUploading.value)return;
  cleanUploading.value=true;cleanProgress.value=0;cleanError.value="";
  const form=new FormData();
  cleanFiles.value.forEach(item=>form.append("files",item));
  form.append("cleanOnly","1");
  if(cleanErase.value)form.append("eraseOnly","1");
  form.append("title",cleanTitle.value.trim()||"Komik Terjemahan");
  form.append("chapter","1");
  try{
    await new Promise<void>((ok,fail)=>{
      const x=new XMLHttpRequest();x.open("POST","/api/tools/translator/jobs");
      const token=getCsrfToken();if(token)x.setRequestHeader("X-CSRF-Token",token);
      x.upload.onprogress=e=>{if(e.lengthComputable)cleanProgress.value=Math.round(e.loaded/e.total*100)};
      x.onload=()=>{const d=JSON.parse(x.responseText||"{}");x.status>=200&&x.status<300?ok():fail(new Error(d.detail||d.error||`Error ${x.status}`))};
      x.onerror=()=>fail(new Error("Upload gagal."));
      x.send(form);
    });
    cleanOpen.value=false;cleanFiles.value=[];cleanTitle.value="";cleanErase.value=false;await refresh();
  }catch(e){cleanError.value=e instanceof Error?e.message:"Gagal membuat job."}
  finally{cleanUploading.value=false}
}
async function submit(){if(!files.value.length||uploading.value)return;if(!selectedComic.value||!selectedChapter.value){error.value="Pilih folder komik dan chapter terlebih dahulu.";return}uploading.value=true;progress.value=0;error.value="";const form=new FormData();files.value.forEach(item=>form.append("files",item));form.append("comic_id",selectedComic.value.id);form.append("chapter_id",selectedChapter.value.id);form.append("title",selectedComic.value.title);form.append("chapter",selectedChapter.value.number);form.append("min_y",String(Math.max(0,minY.value||0)));try{await new Promise<void>((ok,fail)=>{const x=new XMLHttpRequest();x.open("POST","/api/tools/translator/jobs");const token=getCsrfToken();if(token)x.setRequestHeader("X-CSRF-Token",token);x.upload.onprogress=e=>{if(e.lengthComputable)progress.value=Math.round(e.loaded/e.total*100)};x.onload=()=>{const d=JSON.parse(x.responseText||"{}");x.status>=200&&x.status<300?ok():fail(new Error(d.detail||d.error||`Error ${x.status}`))};x.onerror=()=>fail(new Error("Upload gagal."));x.send(form)});files.value=[];await refresh()}catch(e){error.value=e instanceof Error?e.message:"Gagal membuat job."}finally{uploading.value=false}}
async function cancel(job:Job){const running=job.status==="PROCESSING";if(!window.confirm(running?`Stop proses ${name(job)} sekarang? Halaman yang belum selesai tidak akan dilanjutkan.`:`Batalkan ${name(job)}?`))return;try{await api(`/api/tools/translator/jobs/${job.id}/cancel`,{method:"POST"});await refresh()}catch(e){error.value=e instanceof Error?e.message:"Gagal menghentikan job."}}
async function deleteJob(job:Job){if(!window.confirm(`Hapus ${name(job)} beserta seluruh file hasilnya?`))return;try{await api(`/api/tools/translator/jobs/${job.id}`,{method:"DELETE"});if(reviewJob.value?.id===job.id){reviewJob.value=null;currentImage.value=null}await refresh()}catch(e){error.value=e instanceof Error?e.message:"Gagal menghapus job."}}

// Deleting a chapter or a comic is irreversible, so ask the API what would go
// first and put the real numbers in the confirmation. The server refuses while
// a job is PROCESSING; surface that as a plain message instead of a dialog.
const human=(n:number)=>n<1024**2?`${Math.round(n/1024)} KB`:n<1024**3?`${(n/1024**2).toFixed(1)} MB`:`${(n/1024**3).toFixed(2)} GB`;
async function deleteChapter(item:ChapterFolder){
  if(deleting.value)return;
  deleting.value=item.id;error.value="";
  try{
    const info=await api<{job_count:number;bytes:number;has_running_job:boolean}>(`/api/tools/translator/chapters/${item.id}`);
    if(info.has_running_job){error.value=`Chapter ${item.number} sedang diproses. Hentikan dulu sebelum menghapus.`;return}
    if(!window.confirm(`Hapus Chapter ${item.number}?\n\n${info.job_count} job · ${info.bytes?human(info.bytes):"0 KB"} file\n\nSemua hasil terjemahan chapter ini hilang permanen.`))return;
    await api(`/api/tools/translator/chapters/${item.id}`,{method:"DELETE"});
    if(selectedChapter.value?.id===item.id)selectedChapter.value=null;
    await loadChapters(selectedComic.value!);
  }catch(e){error.value=e instanceof Error?e.message:"Gagal menghapus chapter."}finally{deleting.value=""}
}
async function deleteComic(comic:ComicFolder){
  if(deleting.value)return;
  deleting.value=comic.id;error.value="";
  try{
    const info=await api<{chapter_count:number;job_count:number;memory_jobs:number;memory_references:number;bytes:number;has_running_job:boolean}>(`/api/tools/translator/comics/${comic.id}/deletion-preview`);
    if(info.has_running_job){error.value=`${comic.title} punya job yang sedang diproses. Hentikan dulu sebelum menghapus.`;return}
    const memory=info.memory_jobs+info.memory_references;
    if(!window.confirm(`Hapus TOTAL "${comic.title}"?\n\n${info.chapter_count} chapter · ${info.job_count} job · ${info.bytes?human(info.bytes):"0 KB"}${memory?`\n${memory} data memory ikut terhapus`:""}\n\nJudul, semua chapter, dan seluruh hasilnya hilang permanen.`))return;
    await api(`/api/tools/translator/comics/${comic.id}`,{method:"DELETE"});
    if(selectedComic.value?.id===comic.id){selectedComic.value=null;selectedChapter.value=null;chapters.value=[]}
    await refresh();
  }catch(e){error.value=e instanceof Error?e.message:"Gagal menghapus komik."}finally{deleting.value=""}
}
function download(job:Job){window.location.href=`/api/tools/translator/jobs/${job.id}/download?v=${Date.now()}`}
function downloadPage(image:ComicImage){window.location.href=`/api/tools/translator/images/${image.id}/download?v=${Date.now()}`}
// Crop the leftover source banner off a page. The master PNG is never modified:
// the trim is stored per page and applied when the chapter ZIP and the per-page
// download are built, so it can be adjusted or cleared at any time.
const cropTop=ref(0), cropBottom=ref(0), cropSaving=ref(false), cropMessage=ref("");
// `showCropped` switches the editor preview between the full page (so region
// boxes keep their original coordinates while editing) and the delivered result.
// Without it the operator changes a crop and sees nothing move, which reads as
// "the crop did not work" even when the ZIP was rebuilt correctly.
const showCropped=ref(false);
// Job "clean logo" menyimpan halaman asli di metadata/original.png, jadi
// review bisa menampilkan sebelum/sesudah tanpa membuka tool lain.
const showBefore=ref(false);
const isCleanJob=computed(()=>!!(reviewJob.value?.options as any)?.clean_only);
function toggleBefore(){showBefore.value=!showBefore.value;previewKey.value=Date.now()}
function loadCrop(image:ComicImage|null){cropTop.value=Number(image?.crop_top||0);cropBottom.value=Number(image?.crop_bottom||0);cropMessage.value="";showCropped.value=false;showBefore.value=false}
// Toggle between the editable full page and the cropped result. Regions are
// hidden while cropped because their boxes are positioned against the full
// page and would land on the wrong rows after the trim.
function toggleCropped(){showCropped.value=!showCropped.value;previewKey.value=Date.now()}
// Lines and shades drawn over the preview so the operator drags the cut instead
// of guessing a pixel count. Positions are percentages of the rendered page, so
// they stay correct at any preview width.
const cropTopPercent=computed(()=>currentImage.value?cropTop.value/currentImage.value.height*100:0);
const cropBottomPercent=computed(()=>currentImage.value?cropBottom.value/currentImage.value.height*100:0);
const cropRemaining=computed(()=>currentImage.value?Math.max(1,currentImage.value.height-cropTop.value-cropBottom.value):0);
// Drag a cut line. The delta from the grab point is applied instead of jumping
// the line to the cursor, so grabbing anywhere near the line continues from the
// current value — a click on the handle used to snap the value to the click
// position (measured: a 200px crop jumped to 217 on grab, 880 on a 50px move),
// which read as "the line does not work".
function dragCrop(event:PointerEvent, edge:"top"|"bottom"){
  if(!currentImage.value)return;
  const image=(event.currentTarget as HTMLElement).closest(".preview")?.querySelector("img");
  if(!image)return;
  event.preventDefault();
  const rect=image.getBoundingClientRect();
  if(!rect.height)return;
  const height=currentImage.value.height;
  const scale=height/rect.height;
  const startY=event.clientY;
  const startValue=edge==="top"?cropTop.value:cropBottom.value;
  const apply=(clientY:number)=>{
    const delta=Math.round((clientY-startY)*scale);
    if(edge==="top")cropTop.value=Math.max(0,Math.min(startValue+delta,height-1-cropBottom.value));
    else cropBottom.value=Math.max(0,Math.min(startValue-delta,height-1-cropTop.value));
  };
  const move=(moveEvent:PointerEvent)=>apply(moveEvent.clientY);
  const stop=()=>{window.removeEventListener("pointermove",move);window.removeEventListener("pointerup",stop);window.removeEventListener("pointercancel",stop)};
  window.addEventListener("pointermove",move);
  window.addEventListener("pointerup",stop);
  window.addEventListener("pointercancel",stop);
}
// Suggest a cut from the pipeline's own regions: everything the OCR marked
// PRESERVED above the first translated bubble (and below the last) is leftover
// source branding, so those are the natural boundaries. Only suggested where
// such a region actually exists, so a page with no banner keeps 0.
function detectCrop(){
  if(!currentImage.value)return;
  const height=currentImage.value.height;
  const translated=regions.value.filter(region=>region.status!=="PRESERVED").sort((a,b)=>a.bbox.y-b.bbox.y);
  if(!translated.length){cropMessage.value="Tidak ada bubble terjemahan untuk dijadikan patokan.";return}
  const first=translated[0], last=translated[translated.length-1];
  const lastBottom=last.bbox.y+last.bbox.height;
  const above=regions.value.filter(region=>region.status==="PRESERVED"&&region.bbox.y<first.bbox.y);
  const below=regions.value.filter(region=>region.status==="PRESERVED"&&region.bbox.y>=lastBottom);
  cropTop.value=above.length?Math.min(first.bbox.y,height-1):0;
  const bottomEdge=below.length?Math.min(...below.map(region=>region.bbox.y)):height;
  cropBottom.value=Math.max(0,Math.min(height-bottomEdge,height-1-cropTop.value));
  cropMessage.value=above.length||below.length?"Saran diisi dari sisa banner terdeteksi. Geser garis bila perlu.":"Tidak terdeteksi sisa banner di halaman ini.";
}
async function saveCrop(applyToAll:boolean){if(!currentImage.value||cropSaving.value)return;cropSaving.value=true;cropMessage.value="";error.value="";try{const result=await api(`/api/tools/translator/images/${currentImage.value.id}/crop`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({cropTop:cropTop.value,cropBottom:cropBottom.value,applyToAll})}) as {cropTop:number;cropBottom:number;appliedTo:number};currentImage.value.crop_top=result.cropTop;currentImage.value.crop_bottom=result.cropBottom;if(applyToAll)for(const item of images.value){item.crop_top=result.cropTop;item.crop_bottom=result.cropBottom}cropMessage.value=applyToAll?`Potongan diterapkan ke ${result.appliedTo} halaman.`:"Potongan diterapkan.";previewKey.value=Date.now();
    // Show the delivered result right away: the editable preview stays on the
    // full page, so without this the screen would look unchanged after a
    // successful crop and read as a failure.
    if(result.cropTop||result.cropBottom)showCropped.value=true;
    await refresh()}catch(e){error.value=e instanceof Error?e.message:"Gagal menyimpan potongan."}finally{cropSaving.value=false}}
async function openReview(job:Job){try{reviewJob.value=job;images.value=await api(`/api/tools/translator/jobs/${job.id}/images`);const firstReview=Math.max(0,(job.review_pages?.[0]?.page||1)-1);if(images.value[firstReview])await chooseImage(images.value[firstReview]);else if(images.value[0])await chooseImage(images.value[0]);else throw new Error("Belum ada gambar hasil untuk direview.")}catch(e){error.value=e instanceof Error?e.message:"Gagal membuka review."}}
async function chooseImage(image:ComicImage){currentImage.value=image;regions.value=await api(`/api/tools/translator/images/${image.id}/regions`);selected.value=null;previewKey.value=Date.now();loadCrop(image);const target=regions.value.find(r=>r.status==="NEEDS_REVIEW")||regions.value[0];if(target)pickRegion(target)}
function pickRegion(region:Region){selected.value=region;const meta=region.metadata||{};edit.value={translation:region.translation||"",x:region.bbox.x,y:region.bbox.y,width:region.bbox.width,height:region.bbox.height,fontSize:Number(meta.editor_font_size||meta.font_size||20),alignment:String(meta.editor_alignment||"center"),lineSpacing:Number(meta.editor_line_spacing||0.12)}}
async function saveRender(){if(!selected.value||!currentImage.value||rendering.value)return;rendering.value=true;error.value="";try{await api(`/api/tools/translator/regions/${selected.value.id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(edit.value)});await api(`/api/tools/translator/images/${currentImage.value.id}/render`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({regionId:selected.value.id})});await chooseImage(currentImage.value);await refresh()}catch(e){error.value=e instanceof Error?e.message:"Re-render gagal."}finally{rendering.value=false}}
const stage=(j:Job)=>({QUEUED:"Menunggu antrean",WAITING_RESOURCE:"Menunggu RAM",STARTING:"Menyiapkan worker",OCR:"Mendeteksi teks",TRANSLATION:"Menerjemahkan",REMOVAL:"Membersihkan teks",TYPESETTING:"Memasang teks",DONE:j.status==="REVIEW"?"Perlu review":"Selesai"}[j.stage]||j.stage);
const name=(j:Job)=>j.options?.original_filename||`Job ${j.id.slice(0,8)}`;
const reviewPages=(j:Job)=>j.review_pages?.length?`Halaman ${j.review_pages.map(item=>item.page).join(", ")}`:"";
const size=(n:number)=>n<1024**2?`${Math.round(n/1024)} KB`:`${(n/1024**2).toFixed(1)} MB`;
const boxStyle=(r:Region)=>currentImage.value?{left:`${r.bbox.x/currentImage.value.width*100}%`,top:`${r.bbox.y/currentImage.value.height*100}%`,width:`${r.bbox.width/currentImage.value.width*100}%`,height:`${r.bbox.height/currentImage.value.height*100}%`}:{};
function onWtKey(event:KeyboardEvent){if(event.key==="Escape"&&immersive.value)setImmersive(false)}
onMounted(async()=>{await refresh();timer=window.setInterval(async()=>{await refresh();if(memoryOpen.value&&selectedComic.value)await loadMemory()},4000);window.addEventListener("keydown",onWtKey)});onBeforeUnmount(()=>{resetRawDownload();if(timer)clearInterval(timer);window.removeEventListener("keydown",onWtKey);document.documentElement.style.overflow=""});
</script>

<template>
  <Dialog v-model:visible="rawImportOpen" modal header="Pilih RAW untuk diterjemahkan" :style="{width:'560px',maxWidth:'95vw'}" :closable="rawAction!=='import'" :closeOnEscape="rawAction!=='import'">
    <p>{{selectedRawTitle?.title}} ? {{rawChapters.find(item=>item.id===rawChapterId)?.title}}</p>
    <div class="raw-format-options">
      <label :class="{selected:rawDownloadMode==='original'}" @click.prevent="chooseRawMode('original')"><input v-model="rawDownloadMode" type="radio" value="original" :disabled="rawAction==='import'"><span><b>Original</b><small>Terjemahkan file RAW asli dari source.</small><small v-if="rawPreview?.original">{{rawPreview.original.count}} halaman ? tinggi {{rawPreview.original.min_height.toLocaleString('id-ID')}}?{{rawPreview.original.max_height.toLocaleString('id-ID')}} px</small></span></label>
      <label :class="{selected:rawDownloadMode==='joined'}" @click.prevent="chooseRawMode('joined')"><input v-model="rawDownloadMode" type="radio" value="joined" :disabled="rawAction==='import'"><span><b>Gabungan WebP</b><small>Gabungkan RAW terlebih dahulu, lalu terjemahkan. Lossless ? maksimal 15.000 px.</small><small v-if="rawPreview?.joined">{{rawPreview.joined.count}} halaman ? tinggi {{rawPreview.joined.min_height.toLocaleString('id-ID')}}?{{rawPreview.joined.max_height.toLocaleString('id-ID')}} px</small></span></label>
    </div>
    <p v-if="rawAction==='import'" role="status">Menyiapkan {{rawDownloadMode==='joined'?'Gabungan WebP':'Original'}}. Job masuk antrean setelah RAW siap.</p>
    <p v-if="error" class="raw-error" role="alert">{{error}}</p>
    <template #footer><Button label="Batal" severity="secondary" outlined :disabled="rawAction==='import'" @click="rawImportOpen=false"/><Button :label="rawDownloadMode==='joined'?'Gabung & Masukkan Antrean':'Original & Masukkan Antrean'" icon="pi pi-sparkles" :loading="rawAction==='import'" :disabled="!!rawAction" @click="importRaw"/></template>
  </Dialog>
  <div class="toolbar"><div><p class="eyebrow">TOOLS</p><h3>Auto Comic Translator</h3><small>OCR English ke Indonesia, cleaning, lalu typesetting CC Wild Words.</small></div><Button icon="pi pi-refresh" label="Refresh" size="small" text @click="refresh()" /></div>
  <div class="stats"><article><i class="pi pi-language"></i><div><small>Engine</small><b>PaddleOCR CPU</b></div></article><article class="translator-setting" @click="openAiSettings"><i class="pi pi-sparkles"></i><div><small>Translator · klik untuk setting</small><b>9router</b></div><i class="pi pi-cog"></i></article><article><i class="pi pi-list"></i><div><small>Job aktif</small><b>{{active}}</b></div></article><article><i class="pi pi-server"></i><div><small>RAM tersedia</small><b>{{ram}} GB</b></div></article></div>
  <div v-if="aiSettingsOpen" class="memory-modal" @click.self="aiSettingsOpen=false"><section class="ai-settings"><header><div><p class="eyebrow">AI TRANSLATOR</p><h3>Model 9router</h3><small>Provider tetap 9router. Perubahan berlaku untuk job berikutnya.</small></div><Button icon="pi pi-times" text rounded @click="aiSettingsOpen=false" /></header><label>Model utama<input v-model.trim="aiModel" placeholder="ag/gemini-3.8-flash-low"></label><label>Fallback berurutan<input v-model.trim="aiFallbacks" placeholder="model-a,model-b"><small>Pisahkan dengan koma.</small></label><div class="ai-setting-actions"><Button label="Tes koneksi" icon="pi pi-bolt" severity="secondary" outlined :loading="aiTesting" :disabled="!aiModel" @click="testAiModel"/><Button label="Simpan model" icon="pi pi-save" :loading="aiSaving" :disabled="!aiModel" @click="saveAiSettings"/></div><small v-if="aiMessage" class="ai-setting-message">{{aiMessage}}</small></section></div>
  <section class="global-queue">
    <header><div><b><i class="pi pi-list-check"></i> Antrean Global</b><small>Urutan berikutnya berlaku setelah job yang sedang berjalan selesai.</small></div><span>{{globalQueue.length}} aktif</span></header>
    <div v-if="runningJob" class="running-job" aria-label="Job sedang berjalan">
      <div><small><i class="pi pi-spin pi-spinner"></i> Sedang berjalan</small><b>{{runningJob.options?.comic_title||name(runningJob)}}</b><span>Chapter {{runningJob.options?.chapter||'-'}} · {{stage(runningJob)}}</span></div>
      <div class="running-progress"><b>{{Math.round((runningJob.progress||0)*100)}}%</b><Button label="Buka chapter" icon="pi pi-folder-open" size="small" text @click="openJobFolder(runningJob)" /></div>
      <span class="queue-bar"><i :style="{width:Math.round((runningJob.progress||0)*100)+'%'}"></i></span>
    </div>
    <p v-if="queueMessage" class="queue-feedback" role="status">{{queueMessage}}</p>
    <p v-if="queueError" class="queue-feedback queue-error" role="alert">{{queueError}}</p>
    <div v-if="!globalQueue.length" class="queue-empty"><i class="pi pi-check-circle"></i> Tidak ada chapter dalam antrean.</div>
    <p v-else-if="!movableQueue.length" class="queue-empty">Belum ada chapter menunggu.</p>
    <p v-if="movableQueue.length===1" class="queue-empty">Satu chapter menunggu. Tombol pindah aktif ketika ada chapter menunggu lainnya.</p>
    <div v-for="(job,index) in movableQueue" :key="job.id" class="queue-row">
      <span class="queue-number">{{index+1}}</span>
      <button type="button" class="queue-name queue-open" @click="openJobFolder(job)"><b>{{job.options?.comic_title||name(job)}}</b><small>Chapter {{job.options?.chapter||'-'}} · {{stage(job)}}</small></button>
      <span class="queue-progress"><b>Urutan {{index+1}}</b><small>{{job.status==='WAITING_RESOURCE'?'Menunggu kapasitas':'Menunggu'}}</small></span>
      <span class="queue-bar"><i :style="{width:Math.round((job.progress||0)*100)+'%'}"></i></span>
      <span class="queue-move">
        <button type="button" title="Naikkan satu" :aria-label="`Naikkan ${name(job)} satu urutan`" :disabled="movableIndex(job)<=0||!!queueBusy" @click="moveJob(job,'up')"><i class="pi pi-chevron-up"></i></button>
        <button type="button" title="Turunkan satu" :aria-label="`Turunkan ${name(job)} satu urutan`" :disabled="movableIndex(job)>=movableQueue.length-1||!!queueBusy" @click="moveJob(job,'down')"><i class="pi pi-chevron-down"></i></button>
        <button type="button" title="Pindah ke paling atas" :aria-label="`Pindahkan ${name(job)} ke urutan pertama`" :disabled="movableIndex(job)<=0||!!queueBusy" @click="moveJob(job,'top')"><i class="pi pi-angle-double-up"></i></button>
      </span>
    </div>
  </section>
  <section class="library-browser">
    <div class="library-crumb"><button v-if="selectedComic" @click="selectedComic=null;selectedChapter=null;chapters=[]"><i class="pi pi-home"></i> Komik</button><i v-if="selectedComic" class="pi pi-angle-right"></i><button v-if="selectedComic" :class="{active:!selectedChapter}" @click="selectedChapter=null">{{selectedComic.title}}</button><i v-if="selectedChapter" class="pi pi-angle-right"></i><b v-if="selectedChapter">Chapter {{selectedChapter.number}}</b></div>
    <template v-if="!selectedComic"><div class="folder-create"><input v-model.trim="newComicTitle" maxlength="120" placeholder="Judul komik baru"><select v-model="newComicCategory" style="padding:9px;border:1px solid #293241;border-radius:8px;background:#0d131d;color:#fff;min-width:110px"><option value="manga">Manga</option><option value="manhwa">Manhwa</option><option value="manhua">Manhua</option></select><Button label="Buat Komik" icon="pi pi-folder-plus" :loading="creatingFolder" :disabled="!newComicTitle.trim()" @click="createComic" /></div><div class="folder-grid"><div v-for="comic in comics" :key="comic.id" class="folder-card"><button class="folder-open" @click="loadChapters(comic)"><i class="pi pi-folder"></i><span><b>{{comic.title}}</b><small>{{(comic.category||'manhwa').toUpperCase()}} · {{comic.chapter_count}} chapter · {{comic.job_count}} job</small></span><i class="pi pi-chevron-right"></i></button><Button icon="pi pi-trash" severity="danger" size="small" text rounded :loading="deleting===comic.id" :disabled="!!deleting" title="Hapus komik ini beserta semua chapter, job, dan memory-nya" @click.stop="deleteComic(comic)" /></div><div v-if="!comics.length" class="empty">Buat folder komik pertama Anda.</div></div></template>
    <template v-else-if="!selectedChapter"><div class="folder-tools"><b>{{selectedComic.title}}</b><Button label="Ganti Nama Judul" icon="pi pi-pencil" size="small" outlined :loading="creatingFolder" @click="renameComic" /></div><div class="memory-entry"><div><b>Memory {{selectedComic.title}}</b><small>Pelajari istilah dan gaya dari raw + hasil Indonesia chapter sebelumnya.</small></div><Button label="Pelajari Chapter Sebelumnya" icon="pi pi-graduation-cap" severity="help" @click="loadMemory(true)" /></div><div class="folder-create"><input v-model.trim="newChapterNumber" maxlength="40" placeholder="Nomor chapter, contoh: 1"><Button label="Buat Chapter" icon="pi pi-folder-plus" :loading="creatingFolder" :disabled="!newChapterNumber.trim()" @click="createChapter" /></div><div class="folder-grid"><div v-for="item in chapters" :key="item.id" class="folder-card"><button class="folder-open" @click="openChapter(item)"><i class="pi pi-folder-open"></i><span><b>Chapter {{item.number}}</b><small>{{item.job_count}} job terjemahan</small></span><i class="pi pi-chevron-right"></i></button><Button icon="pi pi-trash" severity="danger" size="small" text rounded :loading="deleting===item.id" :disabled="!!deleting" title="Hapus chapter ini beserta semua job dan hasilnya" @click.stop="deleteChapter(item)" /></div><div v-if="!chapters.length" class="empty">Belum ada chapter. Buat Chapter 1 untuk mulai.</div></div></template>
  </section>
  <section class="panel upload"><div style="display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap"><div><small style="display:block;color:#697386;font-size:.73rem">Komik sudah diterjemahkan orang lain?</small><b style="display:block;margin:3px 0"><i class="pi pi-eraser"></i> Bersihkan logo &amp; tempel Ryukomik</b><small style="display:block;color:#697386;font-size:.73rem">Upload ZIP/gambar hasil terjemahan. Tanpa translasi ulang, tanpa OCR teks.</small></div><Button label="Buka Cleaner" icon="pi pi-eraser" size="small" severity="secondary" outlined @click="cleanOpen=true"/></div><div v-if="jobs.some(job=>job.options&&(job.options as any).clean_only)" style="margin-top:10px;font-size:.75rem;color:#697386">Job cleaner yang sedang berjalan muncul di riwayat bawah.</div></section>
<Dialog v-model:visible="cleanOpen" modal header="Clean logo scanlator" :style="{width:'540px',maxWidth:'95vw'}">
  <div style="display:flex;flex-direction:column;gap:12px">
    <label style="display:flex;flex-direction:column;gap:5px;font-size:.78rem;color:#8793a5">Judul (untuk nama job)<input v-model.trim="cleanTitle" maxlength="120" placeholder="Mis. My Fiancé Only Wants My Body" style="padding:9px;border:1px solid #293241;border-radius:8px;background:#0d131d;color:#fff"></label>
    <label style="display:flex;flex-direction:column;gap:5px;font-size:.78rem;color:#8793a5">File (ZIP atau beberapa gambar)<input type="file" multiple accept=".zip,image/png,image/jpeg,image/webp" @change="pickClean" style="font-size:.78rem"></label>
    <label style="display:flex;align-items:center;gap:8px;font-size:.78rem;color:#8793a5"><input v-model="cleanErase" type="checkbox">Hapus logo saja, tanpa menempel branding Ryukomik</label>
    <p v-if="cleanFiles.length" style="margin:0;font-size:.75rem;color:#697386">{{cleanFiles.length}} file dipilih</p>
    <p v-if="cleanUploading" role="status" style="margin:0;font-size:.75rem;color:#60a5fa">Mengunggah {{cleanProgress}}%</p>
    <p v-if="cleanError" class="error" style="margin:0">{{cleanError}}</p>
  </div>
  <template #footer><Button label="Batal" severity="secondary" outlined :disabled="cleanUploading" @click="cleanOpen=false"/><Button label="Bersihkan sekarang" icon="pi pi-eraser" :loading="cleanUploading" :disabled="!cleanFiles.length||cleanUploading" @click="submitClean"/></template>
</Dialog>
<section v-if="selectedComic&&selectedChapter" class="panel upload"><div class="upload-target"><i class="pi pi-book"></i><div><small>Terjemahkan ke</small><b>{{selectedComic.title}} · Chapter {{selectedChapter.number}}</b></div></div><div class="raw-picker"><header><div><b><i class="pi pi-globe"></i> Ambil RAW dari source</b><small>Cari dan masukkan chapter tanpa upload manual.</small></div></header><form class="raw-search" @submit.prevent="searchRaw"><input v-model.trim="rawQuery" minlength="2" maxlength="120" placeholder="Cari judul RAW Inggris"><Button type="submit" label="Cari" icon="pi pi-search" size="small" :loading="rawSearching" :disabled="rawQuery.trim().length<2" /></form><div v-if="rawResults.length" class="raw-fields"><label>Source<select v-model="rawSource" @change="changeRawSource"><option v-for="item in rawSources" :key="item.id" :value="item.id">{{item.name}}</option></select></label><label>Judul<select v-model="rawMangaId" @change="loadRawChapters"><option value="" disabled>Pilih judul</option><option v-for="item in rawTitles" :key="item.source+item.id" :value="item.id">{{item.title}}</option></select></label><label>Chapter<select v-model="rawChapterId" :disabled="!rawMangaId||rawLoadingChapters"><option value="" disabled>{{rawLoadingChapters?'Memuat chapter...':'Pilih chapter'}}</option><option v-for="item in rawChapters" :key="item.id" :value="item.id">{{item.title}}</option></select></label></div><div v-if="rawMangaId&&rawChapterId" class="raw-actions"><span><b>{{selectedRawTitle?.title}}</b><small>{{rawSource}} · {{rawChapters.find(item=>item.id===rawChapterId)?.title}}</small></span><Button label="Unduh ZIP RAW" icon="pi pi-download" severity="secondary" size="small" outlined :loading="rawAction==='download'" :disabled="!!rawAction" @click="openRawDownload"/><Button label="Unduh & Terjemahkan" icon="pi pi-sparkles" size="small" :loading="rawAction==='import'" :disabled="!!rawAction" @click="openRawImport"/></div><div v-if="rawDownloadOpen" class="raw-download-choice">
  <header><b>Pilih format RAW</b></header>
  <p v-if="!rawPreview&&!rawPreparing">Pilih Original atau Gabungan WebP, lalu klik Siapkan ZIP RAW untuk melihat jumlah halaman dan tingginya.</p>
  <p v-if="rawPreparing" role="status">{{rawPreview?.state==='JOINING'?'Original siap. Menggabungkan halaman WebP...':'Mengunduh dan memeriksa ukuran halaman...'}} Ukuran akan muncul setelah siap.</p>
  <div class="raw-format-options">
    <label :class="{selected:rawDownloadMode==='original'}" @click.prevent="chooseRawMode('original')"><input v-model="rawDownloadMode" type="radio" value="original" :disabled="rawAction==='import'"><span><b>Original</b><small>File sumber, tanpa perubahan.</small><small v-if="rawPreview?.original">{{rawPreview.original.count}} halaman ? tinggi {{rawPreview.original.min_height.toLocaleString('id-ID')}}?{{rawPreview.original.max_height.toLocaleString('id-ID')}} px ? {{size(rawPreview.original.bytes)}}</small></span></label>
    <label :class="{selected:rawDownloadMode==='joined'}" @click.prevent="chooseRawMode('joined')"><input v-model="rawDownloadMode" type="radio" value="joined" :disabled="rawAction==='import'"><span><b>Gabungan WebP</b><small>Lossless ? tanpa resize ? maksimal {{(rawPreview?.joined?.height_limit||15000).toLocaleString('id-ID')}} px.</small><small v-if="rawPreview?.joined">{{rawPreview.joined.count}} halaman ? tinggi {{rawPreview.joined.min_height.toLocaleString('id-ID')}}?{{rawPreview.joined.max_height.toLocaleString('id-ID')}} px ? {{size(rawPreview.joined.bytes)}}</small><small v-else>{{rawPreparing?'Jumlah dan tinggi sedang dihitung.':'Jumlah dan tinggi muncul setelah RAW disiapkan.'}}</small></span></label>
  </div>
  <p v-if="rawPrepareError" class="raw-error" role="alert">{{rawPrepareError}}</p>
  <p v-if="rawDownloadMode==='joined'&&rawPreview?.joined?.source_boundary_cuts">{{rawPreview.joined.source_boundary_cuts}} batas mengikuti potongan sumber karena tidak ada sela panel yang aman.</p>
  <p v-if="rawDownloadMode==='joined'&&rawPreview?.joined?.unsafe_cuts">{{rawPreview.joined.unsafe_cuts}} batas perlu diperiksa karena sumber panjang tidak memiliki sela panel aman.</p>
  <details v-if="rawChosenPackage"><summary>Lihat ukuran {{rawChosenPackage.count}} halaman</summary><div class="raw-dimensions"><table><thead><tr><th>Halaman</th><th>Lebar</th><th>Tinggi</th></tr></thead><tbody><tr v-for="page in rawChosenPackage.pages" :key="page.page"><td>{{page.page}}</td><td>{{page.width.toLocaleString('id-ID')}} px</td><td>{{page.height.toLocaleString('id-ID')}} px</td></tr></tbody></table></div></details>
  <Button :label="rawDownloadMode==='joined'?'Unduh Gabungan WebP ZIP':'Unduh Original ZIP'" icon="pi pi-download" :loading="rawAction==='download'" :disabled="!rawChosenPackage||!!rawAction" @click="downloadRaw"/>
  <small>Paket tersedia 30 menit. Ganti format tanpa mengunduh ulang dari source.</small>
</div></div><div class="upload-divider"><span>atau upload manual</span></div><div class="drop" :class="{active:drag}" @click="input?.click()" @drop="dropped" @dragover.prevent="drag=true" @dragleave="drag=false"><i class="pi pi-cloud-upload"></i><b>{{files.length?`${files.length} halaman dipilih`:"Drag RAW/ZIP atau pilih gambar chapter"}}</b><small>{{files.length?size(files.reduce((sum,item)=>sum+item.size,0)):"PNG, JPG, WEBP, ZIP - 60 gambar / 100 MB"}}</small><input ref="input" type="file" multiple accept=".png,.jpg,.jpeg,.webp,.zip" hidden @change="picked" /></div><div v-if="files.length" class="chosen"><span v-for="(item,index) in files" :key="item.name+index">{{item.name}} <button @click="files.splice(index,1)">x</button></span><Button label="Hapus semua" size="small" text severity="danger" @click="files=[]" /></div><label class="min-y"><span>Abaikan area atas (px)</span><input v-model.number="minY" type="number" min="0" step="100"><small>Berlaku untuk semua halaman.</small></label><div v-if="uploading" class="bar"><div :style="{width:progress+'%'}"></div></div><Button label="Mulai terjemahkan chapter" icon="pi pi-sparkles" :loading="uploading" :disabled="!files.length||uploading" @click="submit" /></section>
  <div v-if="error" class="error"><i class="pi pi-exclamation-triangle"></i>{{error}}</div>
  <div v-if="memoryOpen&&memoryError" class="error" style="position:fixed;z-index:1100;top:18px;left:50%;width:min(720px,calc(100% - 36px));transform:translateX(-50%);box-shadow:0 12px 35px rgba(0,0,0,.55)"><i class="pi pi-exclamation-triangle"></i>{{memoryError}}</div>

  <div v-if="memoryOpen&&selectedComic" class="memory-modal" @click.self="memoryOpen=false"><section><header><div><p class="eyebrow">TITLE MEMORY</p><h3>{{selectedComic.title}}</h3></div><Button icon="pi pi-times" text rounded @click="memoryOpen=false" /></header><div class="memory-upload"><label>Jenis referensi<select v-model="memoryMode"><option value="indonesian_only">Indonesia saja</option><option value="paired">Raw + Indonesia</option></select><small>{{memoryMode==='indonesian_only'?'Pelajari gaya, nama, dan konteks; tidak perlu raw.':'Pelajari padanan istilah dari halaman yang berpasangan.'}}</small></label><label>Chapter referensi<input v-model="memoryChapter" placeholder="Contoh: 28" maxlength="40"></label><label v-if="memoryMode==='paired'">ZIP RAW Inggris<input type="file" accept=".zip" @change="rawZip=(($event.target as HTMLInputElement).files||[])[0]||null"><small>{{rawZip?.name||'Belum dipilih'}}</small></label><label>ZIP hasil Indonesia<input type="file" accept=".zip" @change="translatedZip=(($event.target as HTMLInputElement).files||[])[0]||null"><small>{{translatedZip?.name||'Belum dipilih'}}</small></label><div v-if="memoryUploading" class="bar"><div :style="{width:memoryProgress+'%'}"></div></div><Button label="Analisis Chapter" icon="pi pi-sparkles" :loading="memoryUploading" :disabled="!memoryChapter.trim()||(memoryMode==='paired'&&!rawZip)||!translatedZip" @click="uploadMemory" /></div><div class="memory-jobs"><h4>Proses & proposal</h4><article v-for="job in memoryState?.jobs||[]" :key="job.id"><div><b>Chapter {{job.chapter_number}}</b><small>{{job.stage}} · {{Math.round(job.progress*100)}}%</small><small v-if="job.error" class="bad">{{job.error}}</small></div><span class="pill" :class="job.status.toLowerCase()">{{job.status}}</span><Button v-if="job.status==='QUEUED'" label="Batal" size="small" severity="danger" text @click="cancelMemory(job)"/><template v-if="job.status==='WAITING_APPROVAL'&&job.proposal"><div class="memory-preview"><p>{{job.proposal.summary}}</p><p v-if="job.proposal.style_profile?.pronouns">Sapaan: {{job.proposal.style_profile.pronouns}}</p><p v-if="job.proposal.canonical_terms?.length">Istilah referensi: {{job.proposal.canonical_terms.map((item:any)=>item.target).join(', ')}}</p><small v-if="job.proposal.reference_mode==='indonesian_only'">Istilah Indonesia menjadi referensi ejaan; padanan bahasa sumber belum terverifikasi. Periksa nama dan ringkasan sebelum menyimpan.</small></div><details class="memory-details"><summary>Edit proposal</summary><textarea v-model="memoryDrafts[job.id]" spellcheck="false"></textarea></details><div class="memory-summary"><span>{{job.proposal.reference_mode==='indonesian_only'?'Indonesia saja':'Raw + Indonesia'}}</span><span>{{job.proposal.line_count||job.proposal.pair_count||0}} {{job.proposal.reference_mode==='indonesian_only'?'baris referensi':'pasangan'}}</span><span>{{job.proposal.canonical_terms?.length||0}} istilah referensi</span><span>{{job.proposal.terminology?.length||0}} istilah</span><span>{{job.proposal.character_voices?.length||0}} karakter</span></div><Button label="Simpan Memory" icon="pi pi-check" severity="success" @click="approveMemory(job)" /></template></article></div><div class="memory-references"><h4>Referensi aktif</h4><small>Untuk melanjutkan chapter 36, tambahkan chapter Indonesia 33?35 satu per satu. Referensi dipakai setelah disetujui.</small><article v-for="item in memoryState?.references||[]" :key="item.id"><div><b>Chapter {{item.chapter_number}}</b><small>{{item.summary.line_count||item.summary.pair_count||0}} {{item.summary.reference_mode==='indonesian_only'?'baris Indonesia':'pasangan dipelajari'}}</small></div><Button icon="pi pi-trash" severity="danger" text size="small" @click="deleteReference(item.id)" /></article><div v-if="!memoryState?.references.length" class="empty">Belum ada memory yang disetujui.</div></div></section></div>

  <section v-if="reviewJob&&currentImage" class="review-editor">
    <header><div><b>Review: {{name(reviewJob)}}</b><small>{{webtoon?'Mode webtoon: semua halaman tersambung, gulir untuk membaca berurutan.':'Klik kotak bubble untuk mengedit tanpa OCR ulang.'}}</small></div><div class="review-tools"><div class="mode-switch"><button :class="{active:!webtoon}" @click="setWebtoon(false)"><i class="pi pi-window-maximize"></i><span>Halaman</span></button><button :class="{active:webtoon}" @click="setWebtoon(true)"><i class="pi pi-align-justify"></i><span>Webtoon</span></button></div><Button icon="pi pi-download" label="Unduh halaman ini" title="Unduh halaman ini" size="small" outlined @click="downloadPage(currentImage)" /><Button v-if="webtoon" icon="pi pi-expand" label="Layar penuh" title="Layar penuh" size="small" outlined @click="setImmersive(true)" /><Button icon="pi pi-times" text rounded title="Tutup" @click="reviewJob=null" /></div></header>
    <div class="image-tabs"><button v-for="item in images" :key="item.id" :class="{active:item.id===currentImage.id}" @click="jumpToPage(item)">{{item.filename}}</button></div>

    <div v-if="webtoon" class="webtoon-view">
      <article v-for="page in webtoonPages" :id="`wt-${page.id}`" :key="page.id" class="webtoon-page">
        <header class="webtoon-page-head"><b>{{page.filename}}</b><small>{{page.width}}×{{page.height}} · {{page.region_count}} region</small></header>
        <img :src="`/api/tools/translator/images/${page.id}/preview?w=1000&crop=1&v=${previewKey}`" :alt="page.filename" loading="lazy">
      </article>
      <div v-if="!webtoonPages.length" class="empty">Belum ada gambar hasil untuk direview.</div>
    </div>

    <div v-else class="editor-grid"><div class="preview" :class="{cropped:showCropped}"><button v-if="isCleanJob" class="before-toggle" :class="{active:showBefore}" @click="toggleBefore">{{showBefore?'Lihat hasil bersih':'Lihat halaman asli'}}</button><img :src="`/api/tools/translator/images/${currentImage.id}/preview?${showBefore?'variant=original&':''}${showCropped?'crop=1&':''}v=${previewKey}`" :alt="currentImage.filename"><button v-for="region in (showCropped?[]:regions)" :key="region.id" class="region-box" :class="{selected:selected?.id===region.id,warning:region.status==='NEEDS_REVIEW'}" :style="boxStyle(region)" :title="region.source_text" @click="pickRegion(region)"></button>
      <div v-if="!showCropped" class="crop-shade" :style="{height:`${cropTopPercent}%`}"></div>
      <div v-if="!showCropped" class="crop-shade bottom" :style="{height:`${cropBottomPercent}%`}"></div>
      <div v-if="!showCropped" class="crop-line top" :class="{active:cropTop>0}" :style="{top:`${cropTopPercent}%`}" title="Geser untuk memotong bagian atas" @pointerdown="dragCrop($event,'top')"><span>{{cropTop?`Potong atas · ${cropTop}px`:'Potong atas'}}</span></div>
      <div v-if="!showCropped" class="crop-line bottom" :class="{active:cropBottom>0}" :style="{bottom:`${cropBottomPercent}%`}" title="Geser untuk memotong bagian bawah" @pointerdown="dragCrop($event,'bottom')"><span>{{cropBottom?`Potong bawah · ${cropBottom}px`:'Potong bawah'}}</span></div>
    </div>
      <div class="crop-panel">
        <header><b><i class="pi pi-crop"></i> Potong halaman</b><small>Hilangkan sisa logo/banner raw. <b>Geser garis</b> di gambar (atau isi angka) — hasil ikut ke ZIP chapter &amp; unduhan.</small></header>
        <div class="crop-fields">
          <label>Potong atas (px)<input v-model.number="cropTop" type="number" min="0" :max="currentImage.height"></label>
          <label>Potong bawah (px)<input v-model.number="cropBottom" type="number" min="0" :max="currentImage.height"></label>
        </div>
        <Button :label="showCropped?'Kembali ke halaman penuh':'Lihat hasil potongan'" :icon="showCropped?'pi pi-arrow-left':'pi pi-eye'" size="small" severity="help" outlined @click="toggleCropped" />
        <Button label="Deteksi otomatis dari sisa banner" icon="pi pi-search" size="small" severity="secondary" outlined @click="detectCrop" />
        <div class="crop-actions">
          <Button label="Terapkan" icon="pi pi-check" size="small" :loading="cropSaving" :disabled="cropSaving" @click="saveCrop(false)" />
          <Button label="Semua halaman" icon="pi pi-copy" size="small" outlined :loading="cropSaving" :disabled="cropSaving" title="Banner biasanya muncul di semua halaman; terapkan potongan yang sama ke seluruh halaman chapter ini" @click="saveCrop(true)" />
          <Button label="Reset" icon="pi pi-undo" size="small" text :disabled="cropSaving||(!cropTop&&!cropBottom)" @click="cropTop=0;cropBottom=0;saveCrop(false)" />
        </div>
        <small v-if="cropTop||cropBottom" class="crop-active">Aktif: tinggi {{currentImage.height}} → {{cropRemaining}}px ({{cropTop}} atas + {{cropBottom}} bawah)</small>
        <small v-if="cropMessage" class="crop-done">{{cropMessage}}</small>
      </div>
      <form v-if="selected" class="controls" @submit.prevent="saveRender"><label>Original<textarea :value="selected.source_text" readonly></textarea></label><label>Translation<textarea v-model="edit.translation" maxlength="2000"></textarea></label><div class="control-grid"><label>X<input v-model.number="edit.x" type="number" min="0"></label><label>Y<input v-model.number="edit.y" type="number" min="0"></label><label>Width<input v-model.number="edit.width" type="number" min="10"></label><label>Height<input v-model.number="edit.height" type="number" min="10"></label><label>Font size<input v-model.number="edit.fontSize" type="number" min="8" max="96"></label><label>Line spacing<input v-model.number="edit.lineSpacing" type="number" min="0" max="1" step="0.02"></label></div><label>Alignment<select v-model="edit.alignment"><option value="left">Left</option><option value="center">Center</option><option value="right">Right</option></select></label><small v-if="selected.metadata.reason==='REMOVAL_NOT_SAFE'" class="bad">Artwork tidak aman dibersihkan. Region ini tidak dapat di-render otomatis.</small><Button type="submit" label="Simpan dan re-render bubble" icon="pi pi-refresh" :loading="rendering" :disabled="rendering||selected.metadata.reason==='REMOVAL_NOT_SAFE'" /></form>
    </div>
  </section>

  <!-- Immersive webtoon reader: a fixed overlay above the app shell so the
       sidebar and content gutter cannot cover the artwork. -->
  <div v-if="reviewJob&&currentImage&&webtoon&&immersive" class="wt-full" id="wt-full-root">
    <header class="wt-full-bar">
      <div class="wt-full-title"><b>{{name(reviewJob)}}</b><small>{{webtoonPages.length}} halaman · gulir untuk membaca</small></div>
      <div class="wt-full-actions">
        <span class="wt-full-count" ref="wtCounterEl">1 / {{webtoonPages.length}}</span>
        <div class="mode-switch"><button :class="{active:!webtoon}" @click="setWebtoon(false)"><i class="pi pi-window-maximize"></i><span>Halaman</span></button><button :class="{active:webtoon}" @click="setWebtoon(true)"><i class="pi pi-align-justify"></i><span>Webtoon</span></button></div>
        <Button icon="pi pi-compress" label="Keluar layar penuh" size="small" outlined @click="setImmersive(false)" />
      </div>
    </header>
    <div class="wt-full-scroll" id="wt-full-scroll" ref="wtScrollEl" @scroll="onWtScroll">
      <article v-for="page in webtoonPages" :id="`wt-scroll-${page.id}`" :key="page.id" class="wt-full-page">
        <img :src="`/api/tools/translator/images/${page.id}/preview?w=1400&crop=1&v=${previewKey}`" :alt="page.filename" loading="lazy">
      </article>
      <div v-if="!webtoonPages.length" class="empty">Belum ada gambar hasil untuk direview.</div>
    </div>
  </div>

  <section v-if="selectedComic&&selectedChapter" class="history chapter-contents"><header><div><b><i class="pi pi-folder-open"></i> Isi Chapter {{selectedChapter.number}}</b><small>{{selectedComic.title}} · {{selectedChapterJobs.length}} job tersimpan</small></div><small>Update setiap 4 detik</small></header><div v-if="!selectedChapterJobs.length" class="empty"><i class="pi pi-folder"></i><b>Folder chapter masih kosong</b><small>Download RAW dari source atau upload manual untuk membuat job pertama.</small></div><article v-for="job in selectedChapterJobs" :key="job.id"><i class="pi pi-images file-icon"></i><div class="copy"><b>{{name(job)}}</b><small>{{stage(job)}} · {{Math.round((job.progress||0)*100)}}% · {{new Date(job.created_at*1000).toLocaleString('id-ID')}}</small><small v-if="job.error" class="bad">{{job.error}}</small></div><span class="pill" :class="job.status.toLowerCase()">{{job.status.replace('_',' ')}}</span><div class="actions"><Button v-if="['QUEUED','WAITING_RESOURCE','PROCESSING'].includes(job.status)" :label="job.status==='PROCESSING'?'Stop proses':'Batalkan'" :icon="job.status==='PROCESSING'?'pi pi-stop-circle':'pi pi-times'" severity="danger" size="small" :text="job.status!=='PROCESSING'" @click="cancel(job)"/><Button v-if="['COMPLETED','REVIEW'].includes(job.status)" :label="(job.options as any)?.clean_only?'Preview':'Review'" icon="pi pi-pencil" size="small" text @click="openReview(job)"/><span v-if="job.review_count" class="review-count"><b>{{job.review_count}} review</b><small>{{reviewPages(job)}}</small></span><Button v-if="['COMPLETED','REVIEW'].includes(job.status)" :label="job.options?.input_files?.length&&job.options.input_files.length>1?'ZIP':'Unduh'" icon="pi pi-download" size="small" @click="download(job)"/><Button v-if="job.status!=='PROCESSING'" label="Hapus" icon="pi pi-trash" severity="danger" size="small" text @click="deleteJob(job)"/></div></article></section>
</template>

<style scoped>
.translator-setting{cursor:pointer}.translator-setting:hover{border-color:#60a5fa;background:rgba(59,130,246,.08)}
.ai-settings{display:grid;gap:16px;max-width:620px}.ai-settings label{display:grid;gap:7px;color:#b9c7df}.ai-settings input{width:100%;padding:12px;border:1px solid #334155;border-radius:9px;background:#0b1220;color:#fff}.ai-settings label small{color:#7183a3}.ai-setting-actions{display:flex;justify-content:flex-end;gap:10px}.ai-setting-message{padding:10px 12px;border-radius:8px;background:#101d2e;color:#7dd3fc}
.queue-open{border:0;background:transparent;color:inherit;text-align:left;cursor:pointer;padding:0;font:inherit}.queue-open:hover b{color:#7db7ff}.queue-feedback{font-size:.76rem;color:#86efac;margin:10px 0}.queue-error{color:#fca5a5}.running-job{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;padding:13px;margin:10px 0;border:1px solid #2563eb;border-radius:10px;background:rgba(37,99,235,.1)}.running-job small,.running-job b,.running-job span{display:block}.running-job small{color:#93c5fd;font-size:.72rem;margin-bottom:5px}.running-job b{font-size:.85rem}.running-job span{font-size:.72rem;color:#94a3b8;margin-top:5px}.running-job>.queue-bar{grid-column:1/-1}.running-progress{text-align:right}.running-progress b{color:#93c5fd}
.raw-download-choice{margin-top:12px;padding:14px;border:1px solid #38425a;border-radius:10px;background:#101723}.raw-download-choice header{display:flex;justify-content:space-between;align-items:center}.raw-download-choice header button{color:#b5bfd0;background:transparent;border:0;cursor:pointer}.raw-download-choice p,.raw-download-choice>small{font-size:.75rem;color:#9aa8bf}.raw-format-options{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0}.raw-format-options label{display:flex;gap:9px;padding:12px;border:1px solid #344057;border-radius:9px;cursor:pointer}.raw-format-options label.selected{border-color:#a78bfa;background:#211d38}.raw-format-options small{display:block;margin-top:5px;font-size:.72rem;color:#a4b1c5}.raw-dimensions{max-height:220px;overflow:auto;margin:8px 0}.raw-dimensions table{width:100%;border-collapse:collapse;font-size:.75rem}.raw-dimensions th,.raw-dimensions td{padding:6px 9px;text-align:left;border-bottom:1px solid #283348}.raw-download-choice details{margin-bottom:12px}.raw-download-choice>small{display:block;margin-top:9px}.raw-download-choice p.raw-error{color:#fb7185}@media(max-width:600px){.raw-format-options{grid-template-columns:1fr}}
</style>

<style scoped>
.stats{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:16px}.stats article{display:flex;align-items:center;gap:11px;padding:14px;border:1px solid rgba(255,255,255,.06);border-radius:12px;background:rgba(255,255,255,.03)}.stats i{width:35px;height:35px;display:grid;place-items:center;border-radius:9px;background:rgba(79,156,247,.1);color:#4f9cf7}.stats small,.stats b,.drop small,.drop b,.review-editor header small{display:block}.stats small,.drop small,.copy small,.history header small,.review-editor small,.chapter-heading small{color:#697386;font-size:.73rem}.upload{margin-top:14px}.chapter-fields{display:grid;grid-template-columns:2fr 1fr;gap:12px;margin-bottom:14px}.upload .chapter-fields label{display:flex;flex-direction:column;align-items:stretch;gap:6px;margin:0}.drop{padding:28px;text-align:center;border:2px dashed #293241;border-radius:14px;cursor:pointer}.drop.active,.drop:hover{border-color:#4f9cf7}.drop>i{display:block;margin-bottom:8px;font-size:2rem;color:#4f9cf7}.drop small{margin-top:5px}.upload .min-y{display:grid;grid-template-columns:180px 120px 1fr;gap:12px;align-items:center;margin:14px 0;font-size:.8rem}.upload input,.controls input,.controls textarea,.controls select{min-width:0;padding:9px;border:1px solid #293241;border-radius:8px;background:#0d131d;color:#fff}.upload>button{width:100%}.bar{height:6px;margin:12px 0;background:#111827;border-radius:6px;overflow:hidden}.bar div{height:100%;background:#4f9cf7}.error{display:flex;gap:8px;margin-top:12px;padding:11px;border-radius:10px;background:rgba(239,68,68,.08);color:#ef4444}.review-editor{margin-top:18px;padding:14px;border:1px solid rgba(79,156,247,.25);border-radius:14px;background:#0b111a}.review-editor>header,.history>header{display:flex;justify-content:space-between;margin-bottom:10px}.image-tabs{display:flex;gap:6px;overflow:auto;margin-bottom:10px}.image-tabs button{padding:6px 9px;border:1px solid #263244;border-radius:7px;background:#111827;color:#8490a2;cursor:pointer}.image-tabs button.active{border-color:#4f9cf7;color:#fff}.editor-grid{display:grid;grid-template-columns:minmax(260px,420px) 1fr;gap:16px;align-items:start}.preview{position:relative;width:100%;line-height:0;background:#05070b;overflow:hidden}
.before-toggle{position:absolute;top:8px;right:8px;z-index:5;padding:6px 10px;border:1px solid rgba(255,255,255,.25);border-radius:8px;background:rgba(8,13,20,.82);color:#dbe4f0;font-size:.72rem;font-weight:700;cursor:pointer;line-height:1.2}
.before-toggle.active{border-color:#a78bfa;color:#ddd0ff;background:rgba(58,40,92,.9)}.preview img{width:100%;height:auto}.region-box{position:absolute;border:2px solid rgba(59,130,246,.75);background:rgba(59,130,246,.08);cursor:pointer}.region-box.warning{border-color:#f59e0b;background:rgba(245,158,11,.1)}.region-box.selected{border-color:#22c55e;background:rgba(34,197,94,.13)}.controls{display:flex;flex-direction:column;gap:10px}.controls label{display:flex;flex-direction:column;gap:4px;font-size:.76rem;color:#8793a5}.controls textarea{min-height:72px;resize:vertical}.control-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.bad{color:#ef4444!important}.history{margin-top:20px}.chapter-group{margin-bottom:12px;padding:8px;border:1px solid rgba(255,255,255,.07);border-radius:14px;background:rgba(255,255,255,.018)}.chapter-heading{display:flex;align-items:center;gap:10px;padding:5px 6px 10px}.chapter-heading>i{color:#f6b94a}.chapter-heading b,.chapter-heading small{display:block}.history article{display:grid;grid-template-columns:34px minmax(0,1fr) auto;gap:11px;align-items:center;margin-bottom:8px;padding:13px;border:1px solid rgba(255,255,255,.07);border-radius:12px;background:rgba(255,255,255,.025)}.file-icon{display:grid;place-items:center;width:34px;height:34px;border-radius:9px;background:rgba(59,130,246,.1);color:#3b82f6}.copy{min-width:0}.copy>b,.copy small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pill{padding:4px 8px;border-radius:99px;background:#273142;color:#aab2c0;font-size:.65rem;font-weight:800}.pill.completed{color:#22c55e;background:rgba(34,197,94,.12)}.pill.processing{color:#60a5fa;background:rgba(59,130,246,.12)}.pill.review,.pill.waiting_resource{color:#f59e0b;background:rgba(245,158,11,.12)}.pill.failed,.pill.cancelled{color:#ef4444;background:rgba(239,68,68,.1)}.actions{grid-column:2/4;display:flex;justify-content:flex-end;gap:8px;align-items:center}.review-count{font-size:.75rem;color:#f59e0b}.empty{padding:30px;text-align:center;border:1px dashed #293241;border-radius:12px;color:#697386}@media(max-width:720px){.stats{grid-template-columns:1fr 1fr;gap:7px}.stats article{padding:10px 8px;gap:8px}.stats i{width:30px;height:30px}.chapter-fields,.editor-grid{grid-template-columns:1fr}.upload .min-y{grid-template-columns:1fr;gap:6px}.drop{padding:22px 12px}.history>header small{display:none}.chapter-group{padding:6px}.history article{grid-template-columns:34px minmax(0,1fr) auto;padding:11px 9px;gap:9px}.pill{grid-column:3;grid-row:1}.actions{grid-column:1/4;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px}.actions :deep(.p-button){width:100%;min-width:0;padding:.55rem .35rem}.actions :deep(.p-button-label){font-size:.72rem;white-space:nowrap}.review-count{display:flex;align-items:center;justify-content:center}.preview{max-width:420px;margin:auto}}
.global-queue{margin-top:14px;padding:13px;border:1px solid rgba(59,130,246,.2);border-radius:13px;background:#0b111a}.global-queue>header{display:flex;align-items:center;justify-content:space-between;margin-bottom:9px}.global-queue>header b,.global-queue>header small{display:block}.global-queue>header b i{margin-right:6px;color:#60a5fa}.global-queue>header small{margin-top:3px;color:#697386;font-size:.7rem}.global-queue>header>span{padding:4px 8px;border-radius:99px;background:rgba(59,130,246,.12);color:#60a5fa;font-size:.68rem;font-weight:700}.queue-empty{padding:13px;text-align:center;color:#667386;font-size:.76rem}.queue-empty i{margin-right:5px;color:#22c55e}.queue-row{width:100%;display:grid;grid-template-columns:28px minmax(0,1fr) auto 90px auto;gap:9px;align-items:center;margin-top:6px;padding:10px;border:1px solid rgba(255,255,255,.06);border-radius:9px;background:rgba(255,255,255,.025);color:#fff;text-align:left;cursor:pointer}.queue-row:hover{border-color:#4f9cf7;background:rgba(79,156,247,.06)}.queue-number{display:grid;place-items:center;width:25px;height:25px;border-radius:7px;background:#172235;color:#7db7ff;font-size:.7rem;font-weight:800}.queue-name,.queue-progress{min-width:0}.queue-name b,.queue-name small,.queue-progress b,.queue-progress small{display:block}.queue-name b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.78rem}.queue-name small,.queue-progress small{margin-top:2px;color:#718096;font-size:.66rem}.queue-progress{text-align:right}.queue-progress b{font-size:.72rem}.queue-bar{height:4px;border-radius:4px;background:#1d2939;overflow:hidden}.queue-bar i{display:block;height:100%;border-radius:4px;background:#4f9cf7}.queue-row>i{color:#536074;font-size:.68rem}.queue-move{display:flex;gap:3px}.queue-move button{display:grid;place-items:center;width:26px;height:26px;padding:0;border:1px solid #263244;border-radius:7px;background:#111827;color:#8fa3bd;cursor:pointer}.queue-move button:hover:not(:disabled){border-color:#4f9cf7;color:#fff}.queue-move button:disabled{opacity:.32;cursor:default}.queue-move i{font-size:.68rem}@media(max-width:720px){.queue-row{grid-template-columns:25px minmax(0,1fr) auto}.queue-bar{grid-column:2/3;width:100%}.queue-move{grid-column:3;grid-row:1;align-self:center}.queue-move button{width:30px;height:30px}.queue-row>i{grid-column:3;grid-row:1}.global-queue>header small{display:none}}
.chosen{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.chosen span{padding:5px 8px;border-radius:7px;background:#111827;color:#94a3b8;font-size:.72rem}.chosen span button{margin-left:5px;border:0;background:transparent;color:#ef4444;cursor:pointer}
.raw-picker{margin:14px 0;padding:14px;border:1px solid rgba(139,92,246,.28);border-radius:13px;background:rgba(139,92,246,.055)}.raw-picker header b,.raw-picker header small,.raw-actions b,.raw-actions small{display:block}.raw-picker header i{margin-right:5px;color:#a78bfa}.raw-picker header small,.raw-actions small{margin-top:3px;color:#7f8b9e;font-size:.7rem}.raw-search{display:grid;grid-template-columns:1fr auto;gap:8px;margin-top:12px}.raw-search input,.raw-fields select{min-width:0;padding:9px 10px;border:1px solid #293241;border-radius:8px;background:#0d131d;color:#fff}.raw-fields{display:grid;grid-template-columns:.7fr 1.5fr 1fr;gap:9px;margin-top:10px}.raw-fields label{display:flex;flex-direction:column;gap:5px;color:#8793a5;font-size:.7rem}.raw-actions{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px;align-items:center;margin-top:12px;padding-top:11px;border-top:1px solid rgba(255,255,255,.07)}.upload-divider{display:flex;align-items:center;gap:10px;margin:13px 0;color:#596579;font-size:.68rem;text-transform:uppercase;letter-spacing:.08em}.upload-divider:before,.upload-divider:after{content:"";height:1px;flex:1;background:#222d3d}@media(max-width:720px){.raw-search,.raw-fields,.raw-actions{grid-template-columns:1fr}.raw-actions :deep(.p-button){width:100%}}
.chapter-contents>header>div b,.chapter-contents>header>div small,.chapter-contents>.empty b,.chapter-contents>.empty small{display:block}.chapter-contents>.empty>i{display:block;margin-bottom:10px;color:#f6b94a;font-size:2rem}.chapter-contents>.empty b{color:#aab4c3}.chapter-contents>.empty small{margin-top:5px;font-size:.72rem}
.library-browser{margin-top:16px;padding:14px;border:1px solid rgba(255,255,255,.07);border-radius:14px;background:#0b111a}.library-crumb{display:flex;align-items:center;gap:6px;min-height:32px;margin-bottom:12px;overflow:auto;white-space:nowrap}.library-crumb button{padding:6px 8px;border:0;border-radius:7px;background:transparent;color:#8793a5;cursor:pointer}.library-crumb button:hover,.library-crumb button.active{background:#151d2a;color:#fff}.library-crumb>b{font-size:.82rem}.folder-create{display:grid;grid-template-columns:1fr auto;gap:8px;margin-bottom:12px}.folder-create input{min-width:0;padding:10px 12px;border:1px solid #293241;border-radius:9px;background:#0d131d;color:#fff}.folder-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.folder-grid>.empty{grid-column:1/-1}.folder-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px;align-items:center;padding:6px 6px 6px 0;border:1px solid rgba(255,255,255,.07);border-radius:11px;background:rgba(255,255,255,.025);color:#fff}.folder-card:hover{border-color:#4f9cf7;background:rgba(79,156,247,.06)}.folder-open{display:grid;grid-template-columns:38px minmax(0,1fr) 18px;gap:10px;align-items:center;padding:6px 4px 6px 12px;border:0;background:transparent;color:#fff;text-align:left;cursor:pointer;min-width:0}.folder-open>i:first-child{font-size:1.35rem;color:#f6b94a}.folder-open>i:last-child{font-size:.75rem;color:#536074}.folder-card b,.folder-card small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.folder-card small{margin-top:3px;color:#697386;font-size:.7rem}.folder-card>:deep(.p-button){flex:none}.upload-target{display:flex;align-items:center;gap:10px;margin-bottom:12px;padding:10px;border-radius:10px;background:rgba(79,156,247,.08);color:#4f9cf7}.upload-target small,.upload-target b{display:block}.upload-target small{font-size:.68rem;color:#7f8b9e}.upload-target b{color:#fff;font-size:.84rem}@media(max-width:720px){.library-browser{padding:10px}.folder-grid{grid-template-columns:1fr}.folder-create{grid-template-columns:1fr}.folder-create :deep(.p-button){width:100%}.folder-card{padding:11px}.library-crumb{margin-bottom:9px}}
.memory-entry{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px;padding:12px;border:1px solid rgba(139,92,246,.25);border-radius:11px;background:rgba(139,92,246,.07)}.memory-entry b,.memory-entry small{display:block}.memory-entry small{margin-top:3px;color:#8793a5;font-size:.72rem}.memory-modal{position:fixed;inset:0;z-index:1000;display:grid;place-items:center;padding:18px;background:rgba(0,0,0,.75)}.memory-modal>section{width:min(760px,100%);max-height:90vh;overflow:auto;padding:18px;border:1px solid #293241;border-radius:16px;background:#0b111a}.memory-modal header{display:flex;align-items:center;justify-content:space-between}.memory-upload{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0;padding:12px;border-radius:12px;background:#101722}.memory-upload label{display:flex;flex-direction:column;gap:6px;font-size:.75rem;color:#9aa5b5}.memory-upload input,.memory-upload select{min-width:0;padding:9px;border:1px solid #293241;border-radius:8px;background:#0d131d;color:#fff}.memory-upload>button,.memory-upload>.bar{grid-column:1/-1}.memory-jobs article,.memory-references article{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px;align-items:center;margin:8px 0;padding:11px;border:1px solid rgba(255,255,255,.07);border-radius:10px}.memory-jobs b,.memory-jobs small,.memory-references b,.memory-references small{display:block}.memory-jobs small,.memory-references small{color:#778397;font-size:.7rem}.memory-jobs textarea{grid-column:1/-1;min-height:220px;padding:10px;border:1px solid #293241;border-radius:8px;background:#080d14;color:#dbe5f2;font:12px/1.45 monospace;resize:vertical}.memory-summary{grid-column:1/3;display:flex;flex-wrap:wrap;gap:7px}.memory-summary span{padding:5px 8px;border-radius:99px;background:rgba(79,156,247,.1);color:#7db7ff;font-size:.7rem}@media(max-width:720px){.memory-entry{align-items:stretch;flex-direction:column}.memory-entry :deep(.p-button){width:100%}.memory-modal{padding:8px}.memory-modal>section{padding:12px;max-height:96vh}.memory-upload{grid-template-columns:1fr}.memory-jobs article{grid-template-columns:minmax(0,1fr) auto}.memory-jobs textarea,.memory-summary{grid-column:1/-1}.memory-jobs article>:deep(.p-button){grid-column:1/-1;width:100%}}
.review-count{display:flex;flex-direction:column;align-items:flex-end;line-height:1.2}.review-count b{font-size:.75rem}.review-count small{font-size:.64rem;color:#f6b94a;white-space:nowrap}@media(max-width:720px){.review-count{align-items:center;justify-content:center}}
.folder-tools{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px;padding:10px 12px;border-radius:10px;background:rgba(255,255,255,.025)}.folder-tools>b{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}@media(max-width:720px){.folder-tools{align-items:stretch;flex-direction:column}.folder-tools :deep(.p-button){width:100%}}
.review-tools{display:flex;align-items:center;gap:8px}.mode-switch{display:flex;padding:3px;border:1px solid #263244;border-radius:9px;background:#0d131d}.mode-switch button{display:flex;align-items:center;gap:5px;padding:6px 10px;border:0;border-radius:6px;background:transparent;color:#8793a5;font-size:.72rem;font-weight:600;cursor:pointer}.mode-switch button:hover{color:#fff}.mode-switch button.active{background:#1c2941;color:#7db7ff}.mode-switch i{font-size:.72rem}
.crop-panel{display:flex;flex-direction:column;gap:9px;padding:13px;border:1px solid #263244;border-radius:11px;background:#0d131d}
.crop-panel header{display:flex;flex-direction:column;gap:2px}.crop-panel header b{display:flex;align-items:center;gap:7px;font-size:.8rem;color:#c7d0dd}.crop-panel header b i{color:#7db7ff}.crop-panel header small{font-size:.68rem;color:#6d798b;line-height:1.45}
.crop-fields{display:grid;grid-template-columns:1fr 1fr;gap:9px}.crop-fields label{display:flex;flex-direction:column;gap:4px;font-size:.7rem;color:#8793a5}
.crop-fields input{padding:7px 9px;border:1px solid #263244;border-radius:7px;background:#080c13;color:#e6edf6;font-size:.78rem}
.crop-actions{display:flex;flex-wrap:wrap;gap:7px}
.crop-active{font-size:.7rem;color:#f0b37e}.crop-done{font-size:.7rem;color:#66d19e}
/* Draggable cut lines over the preview. The shaded band is exactly what the
   crop removes, so the operator sees the result before applying it. */
.crop-shade{position:absolute;left:0;right:0;top:0;background:rgba(239,68,68,.28);pointer-events:none;z-index:3}
.crop-shade.bottom{top:auto;bottom:0}
.crop-line{position:absolute;left:0;right:0;height:0;border-top:2px dashed #f59e0b;cursor:ns-resize;z-index:4;touch-action:none}
.crop-line.active{border-top-style:solid;border-top-color:#ef4444}
.crop-line span{position:absolute;right:4px;top:-9px;padding:1px 6px;border-radius:5px;background:#f59e0b;color:#1a1205;font-size:.6rem;font-weight:800;white-space:nowrap;pointer-events:none}
/* Labels would be clipped at the page edges, so they move inside the page. */
.crop-line.top span{top:2px}
.crop-line.bottom span{top:auto;bottom:2px}
.crop-line.active span{background:#ef4444;color:#fff}
/* `.preview` has overflow:hidden, so a grab strip reaching outside the page is
   clipped and the line becomes hard (bottom: impossible) to grab. Each strip
   therefore extends 20px to the INSIDE of its line, giving a symmetric target
   that stays within the page at any position. */
.crop-line.top::before{content:"";position:absolute;left:0;right:0;top:0;height:20px}
.crop-line.bottom::before{content:"";position:absolute;left:0;right:0;bottom:0;height:20px}
/* The cropped view shows the delivered result; region boxes are hidden because
   they are positioned against the full page. */
.preview.cropped{outline:2px solid rgba(239,68,68,.35)}
/* Continuous webtoon reader: pages stack full-width with no gap so the strip
   reads like the published source. max-width keeps very wide pages from
   stretching past comfortable line length on large monitors. */
.webtoon-view{display:flex;flex-direction:column;gap:0;max-width:900px;margin:0 auto;border:1px solid rgba(255,255,255,.07);border-radius:12px;overflow:hidden;background:#05070b}
.webtoon-page{position:relative;margin:0;scroll-margin-top:14px}
.webtoon-page+.webtoon-page{border-top:1px solid rgba(255,255,255,.06)}
.webtoon-page-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px;padding:7px 11px;background:#0b111a}.webtoon-page-head b,.webtoon-page-head small{display:block}.webtoon-page-head b{font-size:.74rem;color:#c7d0dd}.webtoon-page-head small{font-size:.66rem;color:#6d798b}
.webtoon-page img{display:block;width:100%;height:auto;background:#05070b}
/* Immersive reader: fixed over the whole viewport (above the 254px sidebar and
   its z-index:5) so the comic strip owns the screen. Only the slim top bar
   overlays the artwork. */
.wt-full{position:fixed;inset:0;z-index:1200;display:flex;flex-direction:column;background:#05070b}
.wt-full-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex:0 0 auto;padding:9px 14px;background:#0b111a;border-bottom:1px solid rgba(255,255,255,.08)}
.wt-full-title b,.wt-full-title small{display:block}.wt-full-title b{font-size:.82rem;color:#e6ebf3}.wt-full-title small{margin-top:2px;font-size:.68rem;color:#6d798b}
.wt-full-actions{display:flex;align-items:center;gap:9px}
.wt-full-count{padding:5px 10px;border-radius:99px;background:rgba(79,156,247,.12);color:#7db7ff;font-size:.72rem;font-weight:700;white-space:nowrap}
.wt-full-scroll{flex:1 1 auto;min-height:0;overflow-y:auto;overscroll-behavior-y:contain;background:#05070b;scroll-behavior:smooth}
.wt-full-page{display:flex;justify-content:center;margin:0}
.wt-full-page img{display:block;width:100%;max-width:min(1200px,100%);height:auto;background:#05070b}
.wt-full .empty{color:#697386;padding:40px;justify-content:center}
@media(max-width:720px){
/* The review header must not eat the screen: the job name is a very long
   filename, so it collapses to a single ellipsised line, the helper text is
   dropped and the tool buttons keep only their icons (they carry a `title`). */
.review-editor>header{flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:8px}
.review-editor>header>div:first-child{flex:1 1 100%;min-width:0}
.review-editor header b{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.86rem}
.review-editor header small{display:none}
.review-tools{width:100%;justify-content:space-between;gap:6px}
.review-tools :deep(.p-button){padding:.45rem .55rem;white-space:nowrap}
.review-tools :deep(.p-button-label){display:none}
.review-tools :deep(.p-button.p-button-icon-only),.review-tools :deep(.p-button-rounded){padding:.45rem}
.mode-switch button{padding:5px 7px;font-size:.66rem}.mode-switch button span{display:none}
.image-tabs{gap:5px;padding-bottom:2px;margin-bottom:8px}
.image-tabs button{padding:5px 8px;font-size:.72rem;white-space:nowrap}
.review-editor{padding:10px;margin-top:10px}
.crop-panel{padding:11px;gap:8px}
.webtoon-view{max-width:none;border-radius:9px}.webtoon-page-head{padding:6px 9px}.webtoon-page-head b{font-size:.68rem}.wt-full-bar{padding:7px 10px;gap:8px}.wt-full-title small{display:none}.wt-full-title b{font-size:.72rem;max-width:38vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.wt-full-actions{gap:6px}.wt-full-count{display:none}}
.raw-download-choice{margin-top:12px;padding:14px;border:1px solid #38425a;border-radius:10px;background:#101723}.raw-download-choice header{display:flex;justify-content:space-between;align-items:center}.raw-download-choice header button{color:#b5bfd0;background:transparent;border:0;cursor:pointer}.raw-download-choice p,.raw-download-choice>small{font-size:.75rem;color:#9aa8bf}.raw-format-options{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0}.raw-format-options label{display:flex;gap:9px;padding:12px;border:1px solid #344057;border-radius:9px;cursor:pointer}.raw-format-options label.selected{border-color:#a78bfa;background:#211d38}.raw-format-options small{display:block;margin-top:5px;font-size:.72rem;color:#a4b1c5}.raw-dimensions{max-height:220px;overflow:auto;margin:8px 0}.raw-dimensions table{width:100%;border-collapse:collapse;font-size:.75rem}.raw-dimensions th,.raw-dimensions td{padding:6px 9px;text-align:left;border-bottom:1px solid #283348}.raw-download-choice details{margin-bottom:12px}.raw-download-choice>small{display:block;margin-top:9px}.raw-download-choice p.raw-error{color:#fb7185}@media(max-width:600px){.raw-format-options{grid-template-columns:1fr}}
</style>

<style scoped>
.memory-preview,.memory-details{grid-column:1/-1}.memory-preview{padding:10px;background:#101722;border-radius:8px;font-size:.8rem;line-height:1.6}.memory-preview p{margin:0 0 6px;white-space:pre-line}.memory-details textarea{width:100%;box-sizing:border-box}.memory-details summary{cursor:pointer;color:#9aa5b5;font-size:.8rem}
.raw-download-choice{margin-top:12px;padding:14px;border:1px solid #38425a;border-radius:10px;background:#101723}.raw-download-choice header{display:flex;justify-content:space-between;align-items:center}.raw-download-choice header button{color:#b5bfd0;background:transparent;border:0;cursor:pointer}.raw-download-choice p,.raw-download-choice>small{font-size:.75rem;color:#9aa8bf}.raw-format-options{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0}.raw-format-options label{display:flex;gap:9px;padding:12px;border:1px solid #344057;border-radius:9px;cursor:pointer}.raw-format-options label.selected{border-color:#a78bfa;background:#211d38}.raw-format-options small{display:block;margin-top:5px;font-size:.72rem;color:#a4b1c5}.raw-dimensions{max-height:220px;overflow:auto;margin:8px 0}.raw-dimensions table{width:100%;border-collapse:collapse;font-size:.75rem}.raw-dimensions th,.raw-dimensions td{padding:6px 9px;text-align:left;border-bottom:1px solid #283348}.raw-download-choice details{margin-bottom:12px}.raw-download-choice>small{display:block;margin-top:9px}.raw-download-choice p.raw-error{color:#fb7185}@media(max-width:600px){.raw-format-options{grid-template-columns:1fr}}
</style>
