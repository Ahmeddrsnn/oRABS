// Oraps 3D Viewer - three.js controller
// Communicates with Python via QWebChannel.

(function() {
'use strict';

// Suppress harmless three.js FileLoader "HTTP Status 0" warning when
// loading from file:// URLs (XHR semantics report status 0 even on success).
(function() {
  const _origWarn = console.warn.bind(console);
  console.warn = function() {
    const first = arguments[0];
    if (typeof first === 'string' && first.indexOf('HTTP Status 0') !== -1) {
      return;
    }
    _origWarn.apply(console, arguments);
  };
})();

const COLOR_OPEN        = 0x10b981; // green
const COLOR_LOCKED      = 0xef4444; // red
const COLOR_SENSOR_OPEN = 0xfacc15; // yellow — DI sensör=1 (fiziksel açık)
const COLOR_BARRIER     = 0xf97316; // orange — aktif ışık bariyeri
const COLOR_NEUTRAL     = 0xcbd5e1; // light grey
const BG_COLOR          = 0x1f2937;

const statusEl   = document.getElementById('status');
const legendEl   = document.getElementById('legend');
const canvasFront = document.getElementById('viewerFront');
const canvasBack  = document.getElementById('viewerBack');
const canvasLeft  = document.getElementById('viewerLeft');
const canvasRight = document.getElementById('viewerRight');
const labelFront  = document.getElementById('labelFront');
const labelBack   = document.getElementById('labelBack');
const labelLeft   = document.getElementById('labelLeft');
const labelRight  = document.getElementById('labelRight');

function setStatus(msg, cls) {
  statusEl.textContent = msg;
  statusEl.className = cls || '';
}

// ── three.js scene ────────────────────────────────────────────────
const scene = new THREE.Scene();
scene.background = new THREE.Color(BG_COLOR);

// Four fixed cameras (front/back/left/right). No OrbitControls — the
// user sees the device like four static photos. Door/port colouring still
// works because every camera shares the same scene + mesh references.
function _newCam() {
  const c = new THREE.PerspectiveCamera(45, 1, 0.1, 100000);
  c.position.set(0, 0, 1);
  return c;
}
const cameraFront = _newCam();
const cameraBack  = _newCam();
const cameraLeft  = _newCam();
const cameraRight = _newCam();

function _newRenderer(canvas) {
  const r = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
  r.setPixelRatio(window.devicePixelRatio || 1);
  r.outputEncoding = THREE.sRGBEncoding;
  return r;
}
const rendererFront = _newRenderer(canvasFront);
const rendererBack  = _newRenderer(canvasBack);
const rendererLeft  = _newRenderer(canvasLeft);
const rendererRight = _newRenderer(canvasRight);

const _allViews = [
  { id: 'front', wrapper: document.getElementById('viewFront'),
    canvas: canvasFront, camera: cameraFront, renderer: rendererFront, enabled: true },
  { id: 'back',  wrapper: document.getElementById('viewBack'),
    canvas: canvasBack,  camera: cameraBack,  renderer: rendererBack,  enabled: true },
  { id: 'left',  wrapper: document.getElementById('viewLeft'),
    canvas: canvasLeft,  camera: cameraLeft,  renderer: rendererLeft,  enabled: true },
  { id: 'right', wrapper: document.getElementById('viewRight'),
    canvas: canvasRight, camera: cameraRight, renderer: rendererRight, enabled: true },
];

// Lights
scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const dl1 = new THREE.DirectionalLight(0xffffff, 0.9);
dl1.position.set(500, 800, 600);
scene.add(dl1);
const dl2 = new THREE.DirectionalLight(0xffffff, 0.35);
dl2.position.set(-400, -200, -400);
scene.add(dl2);

// (Grid intentionally removed — user preferred a clean plain background.)

// ── Layout: enable/disable individual views; grid adapts automatically ──
const _viewsRoot = document.getElementById('views');

function _applyLayout() {
  const enabled = _allViews.filter(function(v) { return v.enabled; });
  const n = enabled.length;
  // Hide disabled wrappers, show enabled ones
  _allViews.forEach(function(v) {
    v.wrapper.style.display = v.enabled ? '' : 'none';
  });
  // Choose grid shape based on visible count
  let cols, rows;
  if (n <= 1)      { cols = 1; rows = 1; }
  else if (n === 2){ cols = 2; rows = 1; }   // 2 views → single row, bigger
  else if (n === 3){ cols = 3; rows = 1; }
  else             { cols = 2; rows = 2; }   // 4 views → 2x2 grid
  _viewsRoot.style.gridTemplateColumns = 'repeat(' + cols + ', 1fr)';
  _viewsRoot.style.gridTemplateRows    = 'repeat(' + rows + ', 1fr)';
  // Trigger a resize so renderers pick up the new canvas client sizes
  // (needs to happen AFTER the browser applies the new grid metrics).
  requestAnimationFrame(function() { resize(); });
}
_applyLayout();

// State
let modelRoot = null;
// modelPivot: modelRoot + sprite gruplarını içeren wrapper. Rotasyon bunun
// üzerinde yapılır; pivot merkezi bbox center'a alındığı için rotasyon
// köşe yerine merkez etrafında olur (Faz-7 fix).
let modelPivot = null;
// Pivot orijini (bbox center) — pan sonrası reset için saklanır.
const _pivotOrigin = new THREE.Vector3();
// doorNodes maps door index -> Array<Mesh> = the REAL door panel mesh(es)
// found by spatial proximity to each KLT-180-AS:N hinge. The panel meshes in
// the GLB are anonymous 'Solid1' nodes — we locate them at load time by
// looking for thin door-sized panels directly under each hinge.
let doorNodes = {};
let portNodes = {};
let doorCentroids = {};   // door_index -> THREE.Vector3 (world centre) — chip default pos
let portCentroids = {};   // port_index -> THREE.Vector3
// 3D kapı/port ad etiketleri (Faz-5): mesh'in üstünde, kameraya bakan sprite.
let doorLabelGroup = null;   // THREE.Group — kapı sprite'ları
let portLabelGroup = null;   // THREE.Group — port sprite'ları
let doorSprites = {};        // door_index -> THREE.Sprite
let portSprites = {};        // port_index -> THREE.Sprite
let _labelScale = 1;         // sprite temel yüksekliği (model bbox'a göre)
let _labelOutward = 0;       // etiketi kabin merkezinden dışa itme mesafesi
const _labelCenterV = new THREE.Vector3();  // model merkezi (dışa ofset için)
let pendingDoorStates = null;
let pendingPortStates = null;
let modelBBox = null;
let unitScale = 1.0;   // 1.0 = cm (default). For mm pass 10, for m pass 0.01.

// Resize — each canvas tracks its own client size
function _resizeOne(canvas, camera, renderer) {
  const w = canvas.clientWidth  || 1;
  const h = canvas.clientHeight || 1;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
function resize() {
  _allViews.forEach(function(v) {
    if (v.enabled) _resizeOne(v.canvas, v.camera, v.renderer);
  });
}
window.addEventListener('resize', resize);
// ResizeObserver: Qt container yeniden boyutlandığında window.resize event'i
// her zaman tetiklenmediği için canvas'ları doğrudan izliyoruz.
try {
  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(function() {
      requestAnimationFrame(resize);
    });
    ro.observe(_viewsRoot);
    _allViews.forEach(function(v) {
      try { ro.observe(v.wrapper); } catch (_) { /* yoksay */ }
    });
  }
} catch (_) { /* eski tarayicilarda yoksay */ }
resize();

// Animate — 15 FPS ile sınırlandırılmış render döngüsü. requestAnimationFrame
// ekran hızında (genelde 60 Hz) tetiklenir; araya zaman kapısı koyarak
// saniyede yalnızca ~15 kare çiziyoruz (CPU/GPU yükünü düşürür).
var _targetFPS = 15;
var _frameInterval = 1000 / _targetFPS;
var _lastFrameTime = 0;
function animate(now) {
  requestAnimationFrame(animate);
  if (now === undefined) now = performance.now();
  if (now - _lastFrameTime < _frameInterval) return;
  // Kayan birikmeyi önlemek için son kare zamanını interval'e hizala.
  _lastFrameTime = now - ((now - _lastFrameTime) % _frameInterval);
  _allViews.forEach(function(v) {
    if (v.enabled) v.renderer.render(scene, v.camera);
  });
}
animate();

// ── Load GLB ──────────────────────────────────────────────────────
function clearModel() {
  if (modelRoot) {
    if (modelPivot) {
      modelPivot.remove(modelRoot);
    } else {
      scene.remove(modelRoot);
    }
    modelRoot.traverse(o => {
      if (o.isMesh) {
        o.geometry && o.geometry.dispose();
        if (o.material) {
          if (Array.isArray(o.material)) o.material.forEach(m => m.dispose());
          else o.material.dispose();
        }
      }
    });
    modelRoot = null;
  }
  if (modelPivot) {
    scene.remove(modelPivot);
    modelPivot = null;
  }
  // 3D kapı/port ad etiketlerini (sprite) temizle
  [doorLabelGroup, portLabelGroup].forEach(function(g) {
    if (!g) return;
    scene.remove(g);
    g.traverse(function(o) {
      if (o.material) {
        if (o.material.map) o.material.map.dispose();
        o.material.dispose();
      }
    });
  });
  doorLabelGroup = null;
  portLabelGroup = null;
  doorSprites = {};
  portSprites = {};
  doorNodes = {};
  portNodes = {};
  doorCentroids = {};
  portCentroids = {};
  modelBBox = null;
}

function loadModel(url) {
  setStatus('Model yükleniyor…');
  clearModel();
  const loader = new THREE.GLTFLoader();
  loader.load(
    url,
    function(gltf) {
      modelRoot = gltf.scene;
      modelRoot.scale.setScalar(unitScale);
      // Faz-7 fix: modelRoot'u bir pivot Group içine sar. Pivot merkezi
      // bbox center'a taşınıp modelRoot local'de karşı ofsetle yerleştirilir
      // (aşağıda, bbox hesabı bitince). Bu sayede pivot rotasyonu = merkez
      // etrafında dönüş.
      modelPivot = new THREE.Group();
      modelPivot.add(modelRoot);
      scene.add(modelPivot);

      // ── Node isim tarama ────────────────────────────────────────
      // YENİ format doğrudan mesh isminden gruplanır (spatial query yok):
      //   Kapılar : CKP-<XX>[-Rev01<Y>|<Y>]  GRUP düğümü → alt Solid mesh'i panel
      //   Portlar : eldiven_port_montaj-Rev01<N>  GRUP düğümü → alt kapak+ring mesh
      // ÖNEMLİ: CKP-01-Rev011 ve eldiven_port_montaj-Rev011 birer Object3D
      // (GRUP) düğümüdür; asıl geometri onların ALTINDAKİ Solid mesh'leridir.
      // Bu yüzden isMesh kontrolü YAPMADAN eşleştirip _collectMeshes ile alt
      // mesh'leri topluyoruz.
      // NOT (port): kapak/ring düğümleri (eldiven_port_kapak, Eldiven_Port)
      // montaj'ın ÇOCUKLARIDIR ve hepsi dedup nedeniyle 'Rev011' (port 1)
      // adını taşır. Bu yüzden SADECE montaj eşleştirilir — kapak/ring zaten
      // montaj'ın alt mesh'leri olarak toplanır. Aksi halde tüm kapaklar
      // port 1'e yığılır (34 mesh hatası).
      // ESKİ format (geriye uyum):
      //   Kapılar : KLT-180-AS:N (hinge) → anonim Solid1 panelleri spatial ile bulunur
      //   Portlar : eldiven port montaj:N
      // NOTE: three.js GLTFLoader ':' / '()' karakterlerini stripler,
      // boşluk → '_'. Yani 'CKP-01-Rev01:1' → 'CKP-01-Rev011',
      // 'KLT-180-AS:1' → 'KLT-180-AS1',
      // 'eldiven_port_montaj-Rev01:1' → 'eldiven_port_montaj-Rev011'.
      const CKP_RE      = /^CKP[-_\s]*(\d{1,2})/i;
      const PORT_NEW_RE = /^eldiven[_\s]*port[_\s]*montaj[-_\s]*Rev01(\d{1,2})/i;
      const DOOR_OLD_RE = /^KLT[-_\s]*180[-_\s]*AS[:_\s-]*(\d+)/i;
      const PORT_OLD_RE = /^eldiven[_\s-]*port[_\s-]*montaj[:_\s-]*(\d+)/i;

      const allNames = [];
      const hingePositions = {};   // eski format için: idx -> world pos
      const allMeshes = [];
      const _assignedMesh = new Set();   // global dedup: bir mesh tek gruba
      const ckpNodes = [];         // {name, obj} — YENİ format kapı instance'ları
      const doorMeta = {};         // door_index -> orijinal CKP düğüm adı

      function _cloneMaterial(child) {
        if (child.material && !child._origCloned) {
          child.material = child.material.clone();
          child._origCloned = true;
          child._defaultColor = child.material.color
            ? child.material.color.getHex()
            : COLOR_NEUTRAL;
        }
      }

      // Grup düğümünün altındaki tüm mesh'leri (dedup ederek) bucket'a topla.
      function _collectMeshes(obj, bucket) {
        obj.traverse(function(child) {
          if (child.isMesh && !_assignedMesh.has(child.uuid)) {
            _cloneMaterial(child);
            bucket.push(child);
            _assignedMesh.add(child.uuid);
          }
        });
      }

      modelRoot.updateMatrixWorld(true);

      const _tmpV = new THREE.Vector3();
      modelRoot.traverse(function(obj) {
        if (obj.isMesh) allMeshes.push(obj);
        if (!obj.name) return;
        allNames.push(obj.name);

        // YENİ format: kapı (CKP-XX-...) → her INSTANCE düğümü AYRI kapıdır.
        // CKP-01'in 4 instance'ı (Rev011..014) 4 ayrı fiziksel kapıdır; bu
        // yüzden burada toplamayıp listeye alıyoruz, traverse sonrası doğal
        // sırayla (CKP-01 < CKP-02 < ...) 1..N sıralı indeks veriyoruz.
        const mCkp = obj.name.match(CKP_RE);
        if (mCkp) {
          ckpNodes.push({ name: obj.name, obj: obj });
          return;   // alt Solid'ler traverse sonrası bu düğümden toplanacak
        }

        // YENİ format: port → SADECE montaj GRUP'u (kapak/ring onun çocuğu)
        const mPortNew = obj.name.match(PORT_NEW_RE);
        if (mPortNew) {
          const idx = parseInt(mPortNew[1], 10);
          if (!portNodes[idx]) portNodes[idx] = [];
          _collectMeshes(obj, portNodes[idx]);
          return;
        }

        // ESKİ format: KLT-180-AS hinge pozisyonu (spatial query için)
        const mHinge = obj.name.match(DOOR_OLD_RE);
        if (mHinge) {
          const idx = parseInt(mHinge[1], 10);
          obj.getWorldPosition(_tmpV);
          hingePositions[idx] = _tmpV.clone();
        }

        // ESKİ format: port (eldiven port montaj:N)
        const mPortOld = obj.name.match(PORT_OLD_RE);
        if (mPortOld) {
          const idx = parseInt(mPortOld[1], 10);
          if (!portNodes[idx]) portNodes[idx] = [];
          _collectMeshes(obj, portNodes[idx]);
        }
      });

      // YENİ format kapıları: CKP adına göre DOĞAL sırala (CKP-1 < CKP-2 <
      // CKP-10) ve her instance'a 1..N sıralı benzersiz kapı indeksi ver.
      // Böylece CKP-01'in 4 instance'ı → kapı 1,2,3,4 (hepsi "kapı 1" değil).
      ckpNodes.sort(function(a, b) {
        return a.name.localeCompare(b.name, undefined,
                                    { numeric: true, sensitivity: 'base' });
      });
      let _doorSeq = 0;
      ckpNodes.forEach(function(cn) {
        const bucket = [];
        _collectMeshes(cn.obj, bucket);
        if (bucket.length === 0) return;   // boş locator → atla
        _doorSeq += 1;
        doorNodes[_doorSeq] = bucket;
        doorMeta[_doorSeq] = cn.name;
      });

      // Boş port gruplarını (mesh içermeyen locator) ele — sayım doğru olsun.
      Object.keys(portNodes).forEach(function(k) {
        if (!portNodes[k] || portNodes[k].length === 0) delete portNodes[k];
      });

      const doorFormat = Object.keys(doorNodes).length > 0
        ? 'CKP-new'
        : (Object.keys(hingePositions).length > 0 ? 'KLT-spatial' : 'none');
      const portFormat = Object.keys(portNodes).length > 0 ? 'auto' : 'none';
      console.log('[DOOR INIT] format=' + doorFormat);
      console.log('[PORT INIT] format=' + portFormat);

      // ── Spatial query + iki geçişli atama (yalnızca ESKİ format) ─
      // Criteria (door = thin upright rectangular slab below the hinge):
      //   - thinnest bbox dimension < 15 cm  (it's a panel, not a block)
      //   - mid dimension >= 30 cm, longest >= 50 cm  (door-sized)
      //   - panel centre is within 1.5 m below the hinge (dy in [-0.1, 1.5])
      //   - panel bbox XZ extents contain or are within 0.4 m of the hinge XZ
      if (doorFormat === 'KLT-spatial') {
        const _meshBox  = new THREE.Box3();
        const _meshSize = new THREE.Vector3();
        const _meshCtr  = new THREE.Vector3();
        const meshInfo  = [];

        // Eldiven port mesh'lerini door candidates'tan dışla — port grubu
        // zaten portNodes'da indekslenmiş; aksi halde küçük kapı bbox'ı port
        // halkasıyla çakışıp portu da boyuyor.
        const _portMeshSet = new Set();
        Object.keys(portNodes).forEach(function(k) {
          portNodes[k].forEach(function(pm) { _portMeshSet.add(pm); });
        });

        allMeshes.forEach(function(m) {
          if (_portMeshSet.has(m)) return;
          _meshBox.setFromObject(m);
          if (_meshBox.isEmpty()) return;
          _meshBox.getSize(_meshSize);
          _meshBox.getCenter(_meshCtr);
          const dims = [_meshSize.x, _meshSize.y, _meshSize.z].sort(function(a, b) { return a - b; });
          if (dims[0] > 0.20) return;
          if (dims[1] < 0.20) return;
          if (dims[2] < 0.30) return;
          if (_meshSize.y < 0.25) return;
          meshInfo.push({
            mesh: m,
            centre: _meshCtr.clone(),
            minX: _meshBox.min.x, maxX: _meshBox.max.x,
            minZ: _meshBox.min.z, maxZ: _meshBox.max.z,
            sizeY: _meshSize.y
          });
        });

        // 1) Her hinge için tüm aday panel mesh'lerini topla ve skorla.
        const hingeCandidates = {};
        Object.keys(hingePositions).forEach(function(k) {
          const idx = parseInt(k, 10);
          const hp = hingePositions[idx];
          const localCandidates = [];
          meshInfo.forEach(function(info) {
            const dy = hp.y - info.centre.y;
            if (dy < -0.1 || dy > 1.5) return;
            const dx = Math.max(0, Math.max(info.minX - hp.x, hp.x - info.maxX));
            const dz = Math.max(0, Math.max(info.minZ - hp.z, hp.z - info.maxZ));
            const dxz = Math.sqrt(dx * dx + dz * dz);
            if (dxz > 0.40) return;
            const score = dxz * 10 - info.sizeY + dy * 0.1;
            localCandidates.push({ info: info, score: score });
          });
          localCandidates.sort(function(a, b) { return a.score - b.score; });
          hingeCandidates[idx] = localCandidates;
        });

        // 2) İKİ GEÇİŞLİ atama — Pass A: benzersiz best; Pass B: overlap-add
        const assignedBest = new Set();
        const assignedAny  = new Set();
        const hingeBest    = {};

        const order = Object.keys(hingeCandidates).map(function(k) {
          const arr = hingeCandidates[k];
          const bs = arr.length ? arr[0].score : Infinity;
          return { idx: parseInt(k, 10), bestScore: bs };
        }).sort(function(a, b) { return a.bestScore - b.bestScore; });

        order.forEach(function(entry) {
          const idx = entry.idx;
          const cands = hingeCandidates[idx];
          if (!cands || cands.length === 0) {
            console.warn('[DOOR INIT] hinge ' + idx +
                         ' için hiç panel adayı yok (KLT-180-AS:' + idx +
                         ' yakınında panel-boyutlu mesh bulunamadı).');
            return;
          }
          let bestInfo = null;
          for (let i = 0; i < cands.length; i++) {
            const uuid = cands[i].info.mesh.uuid;
            if (!assignedBest.has(uuid)) {
              bestInfo = cands[i].info;
              break;
            }
          }
          if (!bestInfo) {
            const topCand = cands[0].info;
            const topName = topCand.mesh.name || topCand.mesh.uuid.slice(0, 8);
            let takenBy = '?';
            Object.keys(hingeBest).forEach(function(k) {
              if (hingeBest[k].mesh.uuid === topCand.mesh.uuid) takenBy = k;
            });
            console.warn('[DOOR INIT] hinge ' + idx + ' için benzersiz panel yok — ' +
                         'en yakın "' + topName + '" zaten kapı ' + takenBy +
                         ' tarafından alınmış. PAYLAŞIMLI kullanılıyor.');
            bestInfo = topCand;
          } else {
            assignedBest.add(bestInfo.mesh.uuid);
            assignedAny.add(bestInfo.mesh.uuid);
          }
          hingeBest[idx] = bestInfo;
          doorNodes[idx] = [];
          _cloneMaterial(bestInfo.mesh);
          doorNodes[idx].push(bestInfo.mesh);
        });

        order.forEach(function(entry) {
          const idx = entry.idx;
          const bestInfo = hingeBest[idx];
          if (!bestInfo) return;
          const cands = hingeCandidates[idx];
          const tol = 0.25;
          for (let i = 0; i < cands.length; i++) {
            const c = cands[i].info;
            if (c.mesh === bestInfo.mesh) continue;
            if (assignedBest.has(c.mesh.uuid)) continue;
            if (assignedAny.has(c.mesh.uuid)) continue;
            const overlapsX = !(c.maxX < bestInfo.minX - tol || c.minX > bestInfo.maxX + tol);
            const overlapsZ = !(c.maxZ < bestInfo.minZ - tol || c.minZ > bestInfo.maxZ + tol);
            if (overlapsX && overlapsZ) {
              _cloneMaterial(c.mesh);
              doorNodes[idx].push(c.mesh);
              assignedAny.add(c.mesh.uuid);
            }
          }
        });
      }

      // Fit all four cameras. Determine which horizontal axis is the LONG
      // one — the wide face of the cabinet sits perpendicular to the short
      // axis, so the ON/ARKA cameras must look along the SHORT horizontal
      // axis. The remaining horizontal axis becomes SOL/SAG.
      const box = new THREE.Box3().setFromObject(modelRoot);
      modelBBox = box;
      const size = new THREE.Vector3();
      const center = new THREE.Vector3();
      box.getSize(size);
      box.getCenter(center);
      const maxDim = Math.max(size.x, size.y, size.z);
      const camY = center.y + size.y * 0.15;

      // ── Kapı/port centroid + dış-yüzey bayrağı (chip overlay için) ──
      // Her kapı/port için mesh bbox merkezini sakla (chip default konumu ÖN
      // kameraya projekte edilerek buradan hesaplanır). Kapılar için ayrıca
      // "dış yüzey mi" sezgiseli: centroid modelin XZ çeperine yakınsa gerçek
      // (kulplu, dışa bakan) kapıdır → default görünür; iç bölme paneli değil.
      function _bboxCenter(meshes) {
        const b = new THREE.Box3();
        const t = new THREE.Box3();
        let has = false;
        for (let i = 0; i < meshes.length; i++) {
          t.setFromObject(meshes[i]);
          if (t.isEmpty()) continue;
          if (!has) { b.copy(t); has = true; } else { b.union(t); }
        }
        if (!has) return null;
        const c = new THREE.Vector3();
        b.getCenter(c);
        return c;
      }
      doorCentroids = {};
      portCentroids = {};
      Object.keys(doorNodes).forEach(function(k) {
        const c = _bboxCenter(doorNodes[k]);
        if (c) doorCentroids[k] = c;
      });
      Object.keys(portNodes).forEach(function(k) {
        const c = _bboxCenter(portNodes[k]);
        if (c) portCentroids[k] = c;
      });
      const _footMin = Math.min(size.x, size.z);
      const _outerMargin = _footMin * 0.18;   // çepere bu kadar yakın → dış kapı
      const doorOuter = {};
      Object.keys(doorCentroids).forEach(function(k) {
        const c = doorCentroids[k];
        const dEdge = Math.min(
          c.x - box.min.x, box.max.x - c.x,
          c.z - box.min.z, box.max.z - c.z
        );
        doorOuter[k] = (dEdge <= _outerMargin);
      });

      // 3D kapı ad etiketleri (sprite) için ölçek + dışa-ofset parametreleri.
      // Yazı yüksekliği model yüksekliğinin ~%6'sı; etiket kabin merkezinden
      // dışa doğru itilir ki ilgili kapının önünde dursun (arkadaki kapıların
      // etiketi o görünümde kabin tarafından örtülür → temiz).
      _labelScale = Math.max(0.001, size.y * 0.06);
      _labelOutward = _footMin * 0.06;
      _labelCenterV.copy(center);

      // Front/back along the SHORT horizontal axis (so we see the wide face)
      let frontAxis;          // 'x' or 'z'
      let sideAxis;
      if (size.x <= size.z) { frontAxis = 'x'; sideAxis = 'z'; }
      else                  { frontAxis = 'z'; sideAxis = 'x'; }

      // Distance scales with the face we're looking at (perp dims).
      // Smaller multipliers → closer camera → cabinet fills more of canvas.
      function _placeCam(cam, axis, sign) {
        const perpA = (axis === 'x') ? size.z : size.x;
        const faceMax = Math.max(perpA, size.y);
        const dist = faceMax * 0.95 + Math.max(size.x, size.z) * 0.13;
        if (axis === 'x') {
          cam.position.set(center.x + sign * dist, camY, center.z);
        } else {
          cam.position.set(center.x, camY, center.z + sign * dist);
        }
        cam.lookAt(center);
        cam.far = Math.max(10000, maxDim * 20);
        cam.updateProjectionMatrix();
      }
      _placeCam(cameraFront, frontAxis, +1);
      _placeCam(cameraBack,  frontAxis, -1);
      _placeCam(cameraLeft,  sideAxis,  -1);
      _placeCam(cameraRight, sideAxis,  +1);

      // Faz-7: pivot recenter. Bbox center'ı modelPivot'ın origin'ine al →
      // pivot rotasyonu artık merkez etrafında olur. Net dünya konumu
      // değişmediği için kameralar, sprite'lar ve centroid'ler geçerliliğini
      // korur.
      if (modelPivot) {
        modelRoot.position.sub(center);
        modelPivot.position.copy(center);
        _pivotOrigin.copy(center);   // pan reset için sakla
      }

      // Replay any door/port states the Python side queued before the model
      // was ready (e.g. user started a batch while the GLB was still loading).
      if (pendingDoorStates) {
        Object.keys(pendingDoorStates).forEach(function(k) {
          setDoorState(parseInt(k, 10), pendingDoorStates[k]);
        });
        pendingDoorStates = null;
      }
      if (pendingPortStates) {
        Object.keys(pendingPortStates).forEach(function(k) {
          setPortState(parseInt(k, 10), pendingPortStates[k]);
        });
        pendingPortStates = null;
      }

      const _doorIdxs  = Object.keys(doorNodes).map(function(k) { return parseInt(k, 10); });
      const _portIdxs  = Object.keys(portNodes).map(function(k) { return parseInt(k, 10); });
      const doorCount  = _doorIdxs.length;
      const portCount  = _portIdxs.length;
      // Python tarafı DB'de 1..maxDoorIdx satırlarını oluşturacak; böylece
      // CKP-XX numaralandırması korunur (CKP-18 varsa DB'de door_index=18).
      const maxDoorIdx = _doorIdxs.length ? Math.max.apply(null, _doorIdxs) : 0;
      setStatus('Model yüklendi · ' + doorCount + ' kapı' +
                (maxDoorIdx > doorCount ? ' (max #' + maxDoorIdx + ')' : '') +
                ' / ' + portCount + ' port', 'ok');
      legendEl.style.display = (doorCount > 0 || portCount > 0) ? 'block' : 'none';

      // ── DEBUG: door-mesh atama özeti ──
      console.log('[DOOR INIT] doorCount=' + doorCount);
      Object.keys(doorNodes).forEach(function(k) {
        const arr = doorNodes[k];
        const names = arr.map(function(m) { return m.name || m.uuid.slice(0, 8); }).join(', ');
        console.log('[DOOR INIT]  door ' + k + ' [' + (doorMeta[k] || '?') +
                    '] → ' + arr.length + ' mesh: ' + names);
      });
      // Hangi mesh birden çok door'a atanmış? (dedup sonrası 0 olmalı)
      const _allDoorMeshes = [];
      Object.keys(doorNodes).forEach(function(k) {
        doorNodes[k].forEach(function(m) { _allDoorMeshes.push({k: k, m: m}); });
      });
      const _seen = new Map();
      _allDoorMeshes.forEach(function(entry) {
        const key = entry.m.uuid;
        if (_seen.has(key)) {
          console.warn('[DOOR INIT] !!! mesh "' + (entry.m.name || key.slice(0,8)) +
                       '" appears in BOTH door ' + _seen.get(key) + ' and ' + entry.k);
        } else {
          _seen.set(key, entry.k);
        }
      });

      // ── DEBUG: port-mesh atama özeti ──
      console.log('[PORT INIT] portCount=' + portCount);
      Object.keys(portNodes).forEach(function(k) {
        console.log('[PORT INIT]  port ' + k + ' → ' + portNodes[k].length + ' mesh');
      });
      if (portCount === 0) {
        const _portHints = allNames.filter(function(n) {
          return /port|eldiven/i.test(n);
        }).slice(0, 30);
        console.log('[PORT INIT] Hiç port eşleşmedi. "port" veya "eldiven" ' +
                    'içeren isimler (ilk 30):', _portHints);
      }

      if (window._py_bridge) {
        // DB'ye kapı + port sayısını gönder (eksik satırlar default etiketle
        // oluşturulsun ki UI'da ve tıklamada tüm kapı/portlar bulunabilsin).
        // meta: dış-yüzey bayrakları → yeni kapı satırlarının default
        // görünürlüğü (iç bölme panelleri gizli gelsin).
        var _meta = '';
        try { _meta = JSON.stringify({ outer: doorOuter }); } catch (e) { _meta = ''; }
        try {
          window._py_bridge.on_model_loaded(doorCount, portCount, _meta);
        } catch (e) {
          // Eski imzalarla geriye uyum
          try { window._py_bridge.on_model_loaded(doorCount, portCount); }
          catch (e2) {
            try { window._py_bridge.on_model_loaded(doorCount); } catch (e3) {}
          }
        }
        // Help debugging when nothing matched
        if (doorCount === 0) {
          try {
            window._py_bridge.on_debug_names(JSON.stringify(allNames));
          } catch (e) {}
        }
      }
      // Also log a sample to the JS console for F12 inspection
      if (doorCount === 0) {
        console.log('[viewer] No doors matched. First 20 node names:',
                    allNames.slice(0, 20));
      }
    },
    function(progress) {
      if (progress.lengthComputable) {
        const pct = Math.round(100 * progress.loaded / progress.total);
        setStatus('Yükleniyor… ' + pct + '%');
      }
    },
    function(err) {
      console.error('GLB load error', err);
      setStatus('Model yüklenemedi: ' + (err && err.message ? err.message : err), 'error');
    }
  );
}

// ── Door colouring API ────────────────────────────────────────────
// Paints the actual GLB door PANEL mesh (anonymous 'Solid1' located by
// spatial query in loadModel) — NOT the small hinge bar.
function setDoorState(idx, state) {
  // state: 'open' | 'locked' | 'sensor_open' | 'barrier' | 'neutral'
  const meshes = doorNodes[idx];
  if (!meshes || meshes.length === 0) return;
  let color;
  if (state === 'open')             color = COLOR_OPEN;
  else if (state === 'locked')      color = COLOR_LOCKED;
  else if (state === 'sensor_open') color = COLOR_SENSOR_OPEN;
  else if (state === 'barrier')     color = COLOR_BARRIER;
  else                              color = COLOR_NEUTRAL;
  meshes.forEach(function(m) {
    if (!m.material) return;
    if (state === 'neutral' && m._defaultColor !== undefined) {
      m.material.color.setHex(m._defaultColor);
    } else if (m.material.color) {
      m.material.color.setHex(color);
    }
    if (m.material.emissive) {
      m.material.emissive.setHex(state === 'neutral' ? 0x000000 : color);
      m.material.emissiveIntensity = state === 'neutral' ? 0 : 0.25;
    }
    m.material.needsUpdate = true;
  });
}

function applyDoorStates(statesObj) {
  // statesObj: { "1": "open", "2": "locked", ... }
  if (!statesObj) return;
  // If the model hasn't loaded yet, remember the request and replay it
  // after loadModel's success callback finishes the spatial query.
  if (Object.keys(doorNodes).length === 0) {
    pendingDoorStates = statesObj;
    return;
  }
  // Reset doors NOT mentioned in statesObj to neutral so they return
  // to grey when their sensor/batch state is cleared.
  Object.keys(doorNodes).forEach(function(k) {
    if (!statesObj.hasOwnProperty(k)) {
      setDoorState(parseInt(k, 10), 'neutral');
    }
  });
  Object.keys(statesObj).forEach(function(k) {
    setDoorState(parseInt(k, 10), statesObj[k]);
  });
}

function resetDoors() {
  Object.keys(doorNodes).forEach(function(k) {
    setDoorState(parseInt(k, 10), 'neutral');
  });
}

// ── Port colouring API (Faz-5: GLT canlı veriden bağlanacak) ─────
// state: 'occupied' | 'empty' | 'motion' | 'neutral'
const COLOR_PORT_OCCUPIED = 0x2563eb; // mavi — cihaz/eldiven takılı (Faz-12)
const COLOR_PORT_EMPTY    = 0xcbd5e1; // grey  — boş
const COLOR_PORT_MOTION   = 0x3b82f6; // blue  — hareket algılandı
const COLOR_PORT_BATCH    = 0x9333ea; // purple — aktif batch üyesi port (test bekleniyor)
const COLOR_PORT_PASS     = 0x10b981; // yeşil  — test geçti (Faz-12)
const COLOR_PORT_FAIL     = 0xb91c1c; // koyu kırmızı — test başarısız
                                      // (kilitli kapı kırmızısı 0xef4444'ten farklı)

function setPortState(idx, state) {
  const meshes = portNodes[idx];
  if (!meshes) return;
  let color;
  if (state === 'occupied')    color = COLOR_PORT_OCCUPIED;
  else if (state === 'motion') color = COLOR_PORT_MOTION;
  else if (state === 'batch')  color = COLOR_PORT_BATCH;
  else if (state === 'pass')   color = COLOR_PORT_PASS;
  else if (state === 'fail')   color = COLOR_PORT_FAIL;
  else if (state === 'empty')  color = COLOR_PORT_EMPTY;
  else                          color = COLOR_NEUTRAL;
  meshes.forEach(function(m) {
    if (m.material && m.material.color) {
      m.material.color.setHex(color);
      m.material.needsUpdate = true;
    }
  });
}

function applyPortStates(statesObj) {
  if (!statesObj) return;
  if (Object.keys(portNodes).length === 0) {
    pendingPortStates = statesObj;
    return;
  }
  Object.keys(statesObj).forEach(function(k) {
    setPortState(parseInt(k, 10), statesObj[k]);
  });
}

function resetPorts() {
  Object.keys(portNodes).forEach(function(k) {
    setPortState(parseInt(k, 10), 'neutral');
  });
}

// ── Pick mode (RFID eşleme / kapı eşleme) ──────────────────
// pickMode: '' | 'port' | 'door'. '' → normal mod (sadece kamera kontrolü).
// Etkin olunca ilgili mesh’e tıklanınca bridge.on_port_picked / on_door_picked
// çağrılır. Dokunmatik ekran uyumlu (pointerdown).
//
// Faz-7: pick modu açıkken kullanıcı ayrıca "🔄 Döndür" butonuyla rotate
// modunu açabilir (setRotateEnabled). Rotate açıkken pointer drag → GLB
// yaw/pitch dönmesi (360°, clamp yok); rotate kapalıyken tıklama → pick.
// View layout (ön/arka vb.) değiştirilmez — kullanıcı ayarlarından geldiği
// gibi kalır. Pick modu kapatılınca modelRoot rotasyonu sıfırlanır.
let pickMode = '';
let _rotateEnabled = false;   // rotate toggle (pick modu içinde)

function setPickMode(modeOrEnabled) {
  // Boolean uyumluluğu: true → 'port', false → ''.
  let next = '';
  if (modeOrEnabled === true)  next = 'port';
  else if (modeOrEnabled === false || modeOrEnabled == null) next = '';
  else next = String(modeOrEnabled || '').toLowerCase();
  if (next !== 'port' && next !== 'door') next = '';

  const wasActive = (pickMode !== '');
  const willBeActive = (next !== '');
  pickMode = next;

  // Exit: rotate'i kapat + modelPivot rotasyon, pan ve zoom'unu sıfırla.
  if (wasActive && !willBeActive) {
    _rotateEnabled = false;
    if (modelPivot) {
      modelPivot.quaternion.identity();
      modelPivot.rotation.set(0, 0, 0);
      modelPivot.position.copy(_pivotOrigin);
      modelPivot.scale.set(1, 1, 1);
    }
  }

  _updatePickCursor();
  let msg = 'Hazır';
  if (pickMode === 'port') msg = '🏷 RFID Eşleme — porta tıklayın · 🔄 ile döndür';
  else if (pickMode === 'door') msg = '🚪 Kapı Eşleme — kapıya tıklayın · 🔄 ile döndür';
  setStatus(msg, pickMode ? 'ok' : '');
}

function setRotateEnabled(on) {
  _rotateEnabled = !!on;
  _updatePickCursor();
}

function _updatePickCursor() {
  let cursor = '';
  if (pickMode && _rotateEnabled) cursor = 'grab';
  else if (pickMode)              cursor = 'crosshair';
  _allViews.forEach(function(v) { v.canvas.style.cursor = cursor; });
}

function _portIndexFromMesh(mesh) {
  for (const k in portNodes) {
    const arr = portNodes[k];
    for (let i = 0; i < arr.length; i++) {
      let n = mesh;
      while (n) {
        if (n === arr[i]) return parseInt(k, 10);
        n = n.parent;
      }
    }
  }
  return null;
}

function _doorIndexFromMesh(mesh) {
  // BUG FIX (Faz-X): Direct array includes — parent-traverse araması hatalı
  // eslemeler üretiyordu (cam/iç kabuk parent zincirleri çakışabilir).
  // Şimdi sadece mesh kimliği eşleşmesi sorgulanır.
  for (const k in doorNodes) {
    if (doorNodes[k].indexOf(mesh) !== -1) {
      console.log('[DOOR PICK] mesh="' + (mesh.name || '?') + '" → door_index=' + k
                  + ' (direct hit)');
      return parseInt(k, 10);
    }
  }
  // Fallback: parent zincirinde yakalanmış bir mesh varsa (raycaster çocuk
  // mesh'e tek tek vurmuş olabilir) yine de çözümlüyoruz.
  for (const k in doorNodes) {
    const arr = doorNodes[k];
    for (let i = 0; i < arr.length; i++) {
      let n = mesh.parent;
      while (n) {
        if (n === arr[i]) {
          console.log('[DOOR PICK] mesh="' + (mesh.name || '?') + '" → door_index=' + k
                      + ' (parent-trace hit: arr[' + i + '].name=' + (arr[i].name || '?') + ')');
          return parseInt(k, 10);
        }
        n = n.parent;
      }
    }
  }
  console.warn('[DOOR PICK] No door matched for mesh="' + (mesh.name || '?') + '"');
  return null;
}

function _onCanvasPick(view, ev) {
  if (!pickMode || !modelRoot) return;
  const rect = view.canvas.getBoundingClientRect();
  const x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
  const y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
  const raycaster = new THREE.Raycaster();
  raycaster.setFromCamera({ x: x, y: y }, view.camera);
  const targets = [];
  const pool = (pickMode === 'door') ? doorNodes : portNodes;
  Object.keys(pool).forEach(function(k) {
    pool[k].forEach(function(m) { targets.push(m); });
  });
  if (targets.length === 0) return;
  const hits = raycaster.intersectObjects(targets, true);
  if (hits.length === 0) return;
  if (pickMode === 'door') {
    const idx = _doorIndexFromMesh(hits[0].object);
    if (idx && window._py_bridge && window._py_bridge.on_door_picked) {
      ev.preventDefault();
      ev.stopPropagation();
      try { window._py_bridge.on_door_picked(idx); } catch (e) {}
    }
  } else {
    const idx = _portIndexFromMesh(hits[0].object);
    if (idx && window._py_bridge && window._py_bridge.on_port_picked) {
      ev.preventDefault();
      ev.stopPropagation();
      try { window._py_bridge.on_port_picked(idx); } catch (e) {}
    }
  }
}

_allViews.forEach(function(v) {
  // Faz-8: pick modu + rotate açıkken:
  //   • SOL click drag  → kamera-relative arcball dönme (her 3 eksende
  //     serbest; kamera up/right eksenleri etrafında delta quaternion
  //     pre-multiply edilir → pivot merkezi etrafında serbest dönme).
  //   • SAĞ click drag  → sadece yatay pan (kamera right vektörü yönünde
  //     modelPivot.position kaydırılır; dikey pan yok).
  //   • Rotate KAPALI ise sol click → pick, sağ click → yok sayılır.
  //   • contextmenu bastırılır (sağ tık menüsü çıkmasın).
  // Pick modu kapalıyken pointer olayları hiçbir şey yapmaz.
  // NOT: ev.button — 0=sol, 2=sağ.
  let _drag = null;
  const DRAG_THRESHOLD_PX = 5;
  const _tmpV1 = new THREE.Vector3();
  const _tmpV2 = new THREE.Vector3();
  const _tmpQPitch = new THREE.Quaternion();
  const _tmpQYaw   = new THREE.Quaternion();
  const _WORLD_UP  = new THREE.Vector3(0, 1, 0);

  // Sağ tık menüsünü bastır (pan sırasında açılmasın).
  v.canvas.addEventListener('contextmenu', function(ev) {
    if (pickMode && _rotateEnabled) {
      ev.preventDefault();
      ev.stopPropagation();
    }
  });

  v.canvas.addEventListener('pointerdown', function(ev) {
    if (!pickMode) return;
    // Rotate kapalıyken sadece sol click pick yapar.
    if (!_rotateEnabled) {
      if (ev.button === 0) _onCanvasPick(v, ev);
      return;
    }
    if (!modelPivot) return;
    if (ev.button !== 0 && ev.button !== 2) return;
    _drag = {
      mode: (ev.button === 2) ? 'pan' : 'rotate',
      startX: ev.clientX, startY: ev.clientY,
      startQuat: modelPivot.quaternion.clone(),
      startPos:  modelPivot.position.clone(),
      moved: false,
    };
    v.canvas.style.cursor = (_drag.mode === 'pan') ? 'move' : 'grabbing';
    try { v.canvas.setPointerCapture(ev.pointerId); } catch (e) {}
    ev.preventDefault();
  });

  v.canvas.addEventListener('pointermove', function(ev) {
    if (!_drag || !pickMode || !_rotateEnabled || !modelPivot) return;
    const dx = ev.clientX - _drag.startX;
    const dy = ev.clientY - _drag.startY;
    if (!_drag.moved &&
        (Math.abs(dx) > DRAG_THRESHOLD_PX || Math.abs(dy) > DRAG_THRESHOLD_PX)) {
      _drag.moved = true;
    }
    if (!_drag.moved) return;

    const rect = v.canvas.getBoundingClientRect();
    const w = rect.width || 1, h = rect.height || 1;

    // Kamera bazlı right & up vektörleri (world uzayı).
    v.camera.getWorldDirection(_tmpV1);          // forward
    _tmpV2.copy(_tmpV1).cross(_WORLD_UP).normalize();   // right = fwd × worldUp
    // Eğer forward ~ ±worldUp (nadir olası) → right sıfır olur; fallback:
    if (_tmpV2.lengthSq() < 1e-8) _tmpV2.set(1, 0, 0);
    const camRight = _tmpV2.clone();
    const camUp = new THREE.Vector3().crossVectors(camRight, _tmpV1).normalize();

    if (_drag.mode === 'rotate') {
      // Kamera-relative arcball: dx → camUp etrafında, dy → camRight etrafında.
      // Delta rotasyonu WORLD uzayında pre-multiply → model her açıdan
      // sezgisel döner (3-eksen serbest).
      const yaw   = (dx / w) * Math.PI * 2;
      const pitch = (dy / h) * Math.PI * 2;
      _tmpQYaw.setFromAxisAngle(camUp, -yaw);
      _tmpQPitch.setFromAxisAngle(camRight, -pitch);
      modelPivot.quaternion
        .copy(_drag.startQuat)
        .premultiply(_tmpQYaw)
        .premultiply(_tmpQPitch);
    } else if (_drag.mode === 'pan') {
      // Yalnızca YATAY pan: dx → kamera right yönünde translate.
      // Ekran genişliği kadar drag ≈ model bbox'ının en büyük yatay boyutu.
      let panScale = 1;
      if (modelBBox) {
        const sz = new THREE.Vector3();
        modelBBox.getSize(sz);
        panScale = Math.max(sz.x, sz.z);
      }
      const shift = camRight.multiplyScalar((dx / w) * panScale);
      modelPivot.position.copy(_drag.startPos).add(shift);
    }
  });

  v.canvas.addEventListener('pointerup', function(ev) {
    if (!_drag) return;
    v.canvas.style.cursor = _rotateEnabled ? 'grab' : (pickMode ? 'crosshair' : '');
    try { v.canvas.releasePointerCapture(ev.pointerId); } catch (e) {}
    _drag = null;
  });

  v.canvas.addEventListener('pointercancel', function() {
    if (_drag) {
      v.canvas.style.cursor = _rotateEnabled ? 'grab' : (pickMode ? 'crosshair' : '');
      _drag = null;
    }
  });

  // Wheel zoom — sadece pick+rotate açıkken çalışır (aksi halde sayfa scroll
  // veya viewer görünümü kullanıcı istemeden kaymaz). Her tıkta %10 adım;
  // clamp 0.1× .. 10×.
  v.canvas.addEventListener('wheel', function(ev) {
    if (!pickMode || !_rotateEnabled || !modelPivot) return;
    ev.preventDefault();
    const ZOOM_STEP = 0.10;
    const factor = (ev.deltaY < 0) ? (1 + ZOOM_STEP) : (1 / (1 + ZOOM_STEP));
    const nextScale = Math.max(0.1, Math.min(10, modelPivot.scale.x * factor));
    modelPivot.scale.setScalar(nextScale);
  }, { passive: false });
});

// ── Enabled views (settings-driven) ──────────────────────────────────
function setEnabledViews(ids) {
  // ids: array like ['front','back']. Unknown ids are ignored.
  if (!ids || !ids.length) ids = ['front', 'back', 'left', 'right'];
  const set = {};
  ids.forEach(function(s) { set[String(s).toLowerCase()] = true; });
  _allViews.forEach(function(v) { v.enabled = !!set[v.id]; });
  _applyLayout();
}

// ── Camera presets ────────────────────────────────────────────────
// Cameras are now fixed (front + back). Presets are kept as no-ops so the
// existing Python API surface stays intact.
function viewFront()  {}
function viewTop()    {}
function viewIso()    {}
function viewReset()  {}

// ── Unit / scale ──────────────────────────────────────────────────
function setUnit(unit) {
  // 'mm' -> scale 1.0, 'cm' -> 1.0 (we just keep raw), 'm' -> 1.0
  // The GLB is loaded as-is; this just adjusts camera framing.
  unitScale = 1.0;
  if (modelRoot) modelRoot.scale.setScalar(unitScale);
}

// ── LAF overlay (Faz-5) ──────────────────────────────────────
// GLB üzerinde sensör değer chip'leri. Three.js render loop'una dokunmaz
// (saf DOM katmanı); GLB titremesi olmaz.
// sensors: [{id, label, unit, value, xPct, yPct}]
function setLafSensors(sensors) {
  var overlay = document.getElementById('lafOverlay');
  if (!overlay) return;
  // Mevcut chip ID'lerini topla
  var existing = {};
  for (var i = 0; i < overlay.children.length; i++) {
    var n = overlay.children[i];
    if (n.dataset && n.dataset.sid) existing[n.dataset.sid] = n;
  }
  var liveIds = {};
  for (var k = 0; k < sensors.length; k++) {
    var s = sensors[k];
    var sid = String(s.id);
    liveIds[sid] = true;
    var chip = existing[sid];
    if (!chip) {
      chip = document.createElement('div');
      chip.className = 'laf-chip';
      chip.dataset.sid = sid;
      var lbl = document.createElement('div');
      lbl.className = 'laf-label';
      lbl.textContent = s.label || ('Sensör ' + sid);
      var val = document.createElement('div');
      val.className = 'laf-value';
      val.textContent = (s.value !== undefined && s.value !== null) ? s.value : '—';
      if (s.unit) {
        var unit = document.createElement('span');
        unit.className = 'laf-unit';
        unit.textContent = s.unit;
        val.appendChild(unit);
      }
      chip.appendChild(lbl);
      chip.appendChild(val);
      overlay.appendChild(chip);
    } else {
      // Etiket/unit değişti mi güncelle (diff'li)
      var lblEl = chip.querySelector('.laf-label');
      if (lblEl && lblEl.textContent !== (s.label || ''))
        lblEl.textContent = s.label || ('Sensör ' + sid);
    }
    // Pozisyon (yüzdelik) — default: ekran ortası (debug için). Çalışınca
    // 5d'de drag-place ile DB'den okunan x/y kullanılacak.
    var xPct = (s.xPct != null) ? s.xPct : 50;
    var yPct = (s.yPct != null) ? s.yPct : (40 + k * 8);
    chip.style.left = xPct + '%';
    chip.style.top = yPct + '%';
  }
  // Listede olmayan chip'leri kaldır (TEST chip korunur).
  for (var id in existing) {
    if (id === '__test__') continue;
    if (!liveIds[id]) overlay.removeChild(existing[id]);
  }
}

// Değer güncelle — sadece text, DOM yeniden inşa edilmez → titreme yok.
function updateLafValue(sid, valueStr, unit) {
  var overlay = document.getElementById('lafOverlay');
  if (!overlay) return;
  var chip = overlay.querySelector('.laf-chip[data-sid="' + sid + '"]');
  if (!chip) return;
  var valEl = chip.querySelector('.laf-value');
  if (!valEl) return;
  // Ana metni güncelle ama unit span'ı koru.
  var unitEl = valEl.querySelector('.laf-unit');
  // Sadece değiştiğinde dokun.
  var current = valEl.firstChild ? valEl.firstChild.textContent : '';
  if (current !== valueStr) {
    if (valEl.firstChild && valEl.firstChild.nodeType === Node.TEXT_NODE) {
      valEl.firstChild.textContent = valueStr;
    } else {
      valEl.insertBefore(document.createTextNode(valueStr),
                         valEl.firstChild || null);
    }
  }
  if (unit && unitEl && unitEl.textContent !== unit) {
    unitEl.textContent = unit;
  }
}

// ── LAF chip drag-place modu (Faz-5d) ───────────────────────
var lafEditMode = false;

function setLayoutEditMode(enabled) {
  lafEditMode = !!enabled;
  var overlay = document.getElementById('lafOverlay');
  if (!overlay) return;
  // overlay'in pointer-events'ı default: none (mouse three.js'e geçsin).
  // Edit modunda chip'lere mouse açılır ama overlay'in kendisi yine none.
  var chips = overlay.querySelectorAll('.laf-chip');
  for (var i = 0; i < chips.length; i++) {
    var chip = chips[i];
    if (lafEditMode) {
      chip.style.pointerEvents = 'auto';
      chip.style.cursor = 'grab';
      chip.style.outline = '2px dashed #2563eb';
      _lafAttachDrag(chip);
    } else {
      chip.style.pointerEvents = 'none';
      chip.style.cursor = 'default';
      chip.style.outline = 'none';
      _lafDetachDrag(chip);
    }
  }
}

function _lafAttachDrag(chip) {
  if (chip._lafDragHandler) return;
  function onDown(e) {
    e.preventDefault();
    e.stopPropagation();
    var overlay = document.getElementById('lafOverlay');
    var rect = overlay.getBoundingClientRect();
    var startX = e.clientX;
    var startY = e.clientY;
    var origLeft = parseFloat(chip.style.left) || 50;
    var origTop = parseFloat(chip.style.top) || 50;
    chip.style.cursor = 'grabbing';
    function onMove(ev) {
      ev.preventDefault();
      var dxPct = (ev.clientX - startX) / rect.width * 100;
      var dyPct = (ev.clientY - startY) / rect.height * 100;
      var newLeft = Math.max(2, Math.min(98, origLeft + dxPct));
      var newTop = Math.max(2, Math.min(98, origTop + dyPct));
      chip.style.left = newLeft + '%';
      chip.style.top = newTop + '%';
    }
    function onUp(ev) {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      chip.style.cursor = 'grab';
      var finalLeft = parseFloat(chip.style.left);
      var finalTop = parseFloat(chip.style.top);
      var sid = parseInt(chip.dataset.sid, 10);
      // Python'a bildir
      if (window._py_bridge && window._py_bridge.on_laf_position_changed) {
        try {
          window._py_bridge.on_laf_position_changed(sid, finalLeft, finalTop);
        } catch (err) {
          console.warn('on_laf_position_changed failed:', err);
        }
      }
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }
  chip._lafDragHandler = onDown;
  chip.addEventListener('mousedown', onDown);
}

function _lafDetachDrag(chip) {
  if (chip._lafDragHandler) {
    chip.removeEventListener('mousedown', chip._lafDragHandler);
    chip._lafDragHandler = null;
  }
}

// setLafSensors yeni chip oluşturduktan sonra edit mode aktif olabilir —
// chip'lerin pointer-events ve drag handler'ını tekrar uygulamak gerek.
var _origSetLafSensors = setLafSensors;
setLafSensors = function(sensors) {
  _origSetLafSensors(sensors);
  if (lafEditMode) setLayoutEditMode(true);  // re-apply drag handlers
};

// ── 3D kapı/port ad etiketleri (sprite) + sürükleme — Faz-5 ─────────
// Adı mesh'in üstünde, kameraya bakan yazı olarak koyar. YALNIZCA adı olan
// (kullanıcı isimlendirmiş) öğeler gösterilir. Konum: centroid + kayıtlı
// ofset (yoksa dışa-ofset default). Yerleşim Modu'nda raycast ile sürüklenip
// taşınır → Python'a (dx,dy,dz) ofset kaydedilir. GLB'ye dokunmaz.
var _labelEditMode = false;
var _lastLabelItems = { door: [], port: [] };

function _labelGroupFor(kind) {
  // Faz-7: label group'ları modelRoot altına eklenir → modelPivot rotasyonu
  // sprite'ları da beraber döndürür (aksi halde label'lar sabit kalıp
  // model dönerken kayardı). Fallback (model henüz yoksa): scene'e ekle.
  var parent = modelRoot || scene;
  if (kind === 'door') {
    if (!doorLabelGroup) { doorLabelGroup = new THREE.Group(); parent.add(doorLabelGroup); }
    return doorLabelGroup;
  }
  if (!portLabelGroup) { portLabelGroup = new THREE.Group(); parent.add(portLabelGroup); }
  return portLabelGroup;
}
function _spritesFor(kind)   { return kind === 'door' ? doorSprites : portSprites; }
function _centroidsFor(kind) { return kind === 'door' ? doorCentroids : portCentroids; }

function _labelStateColor(state) {
  switch (state) {
    case 'open':                       return '#10b981';
    case 'occupied':                   return '#2563eb';
    case 'locked':                     return '#ef4444';
    case 'sensor': case 'sensor_open': return '#facc15';
    case 'barrier':                    return '#f97316';
    case 'batch':                      return '#9333ea';
    case 'pass':                       return '#10b981';
    case 'fail':                       return '#b91c1c';
    case 'motion':                     return '#3b82f6';
    default:                           return '#94a3b8';
  }
}

function _roundRectPath(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function _makeLabelTexture(label, sub, accent, kind) {
  // İkon boyutları (kapı = dikey dikdörtgen, port = elips halka).
  var pad = 18, gap = 12;
  var iconW = (kind === 'port') ? 30 : 22;   // port halkası biraz daha geniş
  var iconH = (kind === 'port') ? 30 : 42;   // kapı ikonu portrede yüksek
  var c = document.createElement('canvas');
  var ctx = c.getContext('2d');
  var fLabel = 'bold 42px "Segoe UI", Arial, sans-serif';
  var fSub = '30px "Segoe UI", Arial, sans-serif';
  ctx.font = fLabel; var wl = ctx.measureText(label || '').width;
  ctx.font = fSub;   var ws = sub ? ctx.measureText(sub).width : 0;
  var textW = Math.max(wl, ws);
  var W = Math.ceil(pad * 2 + iconW + gap + textW);
  var H = Math.max(sub ? 116 : 76, iconH + pad);
  c.width = W; c.height = H;
  ctx.clearRect(0, 0, W, H);
  _roundRectPath(ctx, 1, 1, W - 2, H - 2, 12);
  ctx.fillStyle = 'rgba(255,255,255,0.95)'; ctx.fill();
  ctx.lineWidth = 2; ctx.strokeStyle = 'rgba(0,0,0,0.18)'; ctx.stroke();
  // Durum renkli ikon (kapı: küçük dikdörtgen; port: içi boş elips)
  var ix = pad;
  var iy = Math.round((H - iconH) / 2);
  ctx.fillStyle = accent;
  ctx.strokeStyle = accent;
  if (kind === 'port') {
    // Halka (dış elips + iç elips ile "delik" görünümü)
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.ellipse(ix + iconW / 2, iy + iconH / 2,
                iconW / 2 - 2, iconH / 2 - 2, 0, 0, Math.PI * 2);
    ctx.stroke();
    // İçini soluk doldur → "port ağzı" hissi
    ctx.save();
    ctx.globalAlpha = 0.25;
    ctx.beginPath();
    ctx.ellipse(ix + iconW / 2, iy + iconH / 2,
                iconW / 2 - 5, iconH / 2 - 5, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  } else {
    // Küçük kapı: yuvarlak köşeli dikdörtgen + iç çerçeve (kapı paneli)
    _roundRectPath(ctx, ix, iy, iconW, iconH, 3);
    ctx.fill();
    // Kulp noktası (koyu, sağ kenarda küçük daire)
    ctx.save();
    ctx.fillStyle = 'rgba(0,0,0,0.35)';
    ctx.beginPath();
    ctx.arc(ix + iconW - 5, iy + iconH / 2, 2.2, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
  var tx = ix + iconW + gap;
  ctx.textBaseline = 'top';
  ctx.fillStyle = '#111827'; ctx.font = fLabel;
  ctx.fillText(label || '', tx, sub ? 16 : Math.round((H - 42) / 2));
  if (sub) {
    ctx.fillStyle = '#6b7280'; ctx.font = fSub;
    ctx.fillText(sub, tx, 66);
  }
  var tex = new THREE.CanvasTexture(c);
  tex.minFilter = THREE.LinearFilter;
  tex.needsUpdate = true;
  return { texture: tex, w: W, h: H };
}

function _defaultLabelPos(kind, idx) {
  var c = _centroidsFor(kind)[idx];
  if (!c) return null;
  var dx = c.x - _labelCenterV.x, dz = c.z - _labelCenterV.z;
  var dl = Math.sqrt(dx * dx + dz * dz);
  if (dl > 1e-6) { dx /= dl; dz /= dl; } else { dx = 0; dz = 1; }
  return new THREE.Vector3(
    c.x + dx * _labelOutward, c.y + _labelScale * 0.6, c.z + dz * _labelOutward
  );
}

function _setNameLabels(kind, items) {
  _lastLabelItems[kind] = items || [];
  var group = _labelGroupFor(kind);
  var sprites = _spritesFor(kind);
  var centroids = _centroidsFor(kind);
  var live = {};
  for (var i = 0; i < _lastLabelItems[kind].length; i++) {
    var it = _lastLabelItems[kind][i];
    var idx = String(it.index);
    var label = (it.label || '').trim();
    if (!label) continue;              // isimsiz → gösterme
    var c = centroids[idx];
    if (!c) continue;
    live[idx] = true;
    var accent = _labelStateColor(it.state);
    var sub = it.sub || '';
    var sig = label + '|' + sub + '|' + accent + '|' + kind;
    var spr = sprites[idx];
    if (!spr || spr._sig !== sig) {
      if (spr) {
        group.remove(spr);
        if (spr.material) {
          if (spr.material.map) spr.material.map.dispose();
          spr.material.dispose();
        }
      }
      var t = _makeLabelTexture(label, sub, accent, kind);
      var mat = new THREE.SpriteMaterial({
        map: t.texture, transparent: true, depthTest: true, depthWrite: false
      });
      spr = new THREE.Sprite(mat);
      spr._aspect = t.w / t.h;
      spr._sig = sig;
      spr.renderOrder = 999;
      spr._kind = kind;
      spr._idx = it.index;
      group.add(spr);
      sprites[idx] = spr;
    }
    spr.scale.set(_labelScale * spr._aspect, _labelScale, 1);
    var pos;
    if (it.offset && it.offset.x != null) {
      pos = new THREE.Vector3(c.x + it.offset.x, c.y + it.offset.y, c.z + it.offset.z);
    } else {
      pos = _defaultLabelPos(kind, idx);
    }
    if (pos) spr.position.copy(pos);
  }
  Object.keys(sprites).forEach(function(k) {
    if (!live[k]) {
      var s = sprites[k];
      group.remove(s);
      if (s.material) {
        if (s.material.map) s.material.map.dispose();
        s.material.dispose();
      }
      delete sprites[k];
    }
  });
}

function setDoorNameLabels(items) { _setNameLabels('door', items); }
function setPortNameLabels(items) { _setNameLabels('port', items); }

function setLabels3DVisible(on) {
  if (doorLabelGroup) doorLabelGroup.visible = !!on;
  if (portLabelGroup) portLabelGroup.visible = !!on;
}
function setDoorLabels3DVisible(on) { setLabels3DVisible(on); }  // geriye uyum

// ── 3D sürükleme (raycast) — Yerleşim Modu ──────────────────────────
var _labelRaycaster = new THREE.Raycaster();
var _labelDrag = null;   // {sprite, view, plane}

function _viewAtPoint(cx, cy) {
  for (var i = 0; i < _allViews.length; i++) {
    var v = _allViews[i];
    if (!v.enabled) continue;
    var r = v.canvas.getBoundingClientRect();
    if (cx >= r.left && cx <= r.right && cy >= r.top && cy <= r.bottom) {
      return { view: v, rect: r };
    }
  }
  return null;
}
function _ndcInRect(rect, cx, cy) {
  return new THREE.Vector2(
    ((cx - rect.left) / rect.width) * 2 - 1,
    -(((cy - rect.top) / rect.height) * 2 - 1)
  );
}
function _allLabelSprites() {
  var arr = [];
  [doorSprites, portSprites].forEach(function(m) {
    Object.keys(m).forEach(function(k) { arr.push(m[k]); });
  });
  return arr;
}

function _onLabelMouseDown(e) {
  if (!_labelEditMode) return;
  var hit = _viewAtPoint(e.clientX, e.clientY);
  if (!hit) return;
  var ndc = _ndcInRect(hit.rect, e.clientX, e.clientY);
  _labelRaycaster.setFromCamera(ndc, hit.view.camera);
  var isects = _labelRaycaster.intersectObjects(_allLabelSprites(), false);
  if (!isects.length) return;
  e.preventDefault();
  e.stopPropagation();
  var spr = isects[0].object;
  var n = new THREE.Vector3();
  hit.view.camera.getWorldDirection(n);
  var plane = new THREE.Plane().setFromNormalAndCoplanarPoint(n, spr.position.clone());
  _labelDrag = { sprite: spr, view: hit.view, plane: plane };
  document.addEventListener('mousemove', _onLabelMouseMove);
  document.addEventListener('mouseup', _onLabelMouseUp);
}
function _onLabelMouseMove(e) {
  if (!_labelDrag) return;
  e.preventDefault();
  var rect = _labelDrag.view.canvas.getBoundingClientRect();
  var ndc = _ndcInRect(rect, e.clientX, e.clientY);
  _labelRaycaster.setFromCamera(ndc, _labelDrag.view.camera);
  var p = new THREE.Vector3();
  if (_labelRaycaster.ray.intersectPlane(_labelDrag.plane, p)) {
    _labelDrag.sprite.position.copy(p);
  }
}
function _onLabelMouseUp() {
  document.removeEventListener('mousemove', _onLabelMouseMove);
  document.removeEventListener('mouseup', _onLabelMouseUp);
  if (!_labelDrag) return;
  var spr = _labelDrag.sprite;
  var kind = spr._kind, idx = spr._idx;
  var c = _centroidsFor(kind)[String(idx)];
  var ox = spr.position.x - (c ? c.x : 0);
  var oy = spr.position.y - (c ? c.y : 0);
  var oz = spr.position.z - (c ? c.z : 0);
  var arr = _lastLabelItems[kind];
  for (var i = 0; i < arr.length; i++) {
    if (arr[i].index === idx) { arr[i].offset = { x: ox, y: oy, z: oz }; break; }
  }
  var fn = (kind === 'door') ? 'on_door_position_changed' : 'on_port_position_changed';
  if (window._py_bridge && window._py_bridge[fn]) {
    try { window._py_bridge[fn](idx, ox, oy, oz); }
    catch (err) { console.warn(fn + ' failed', err); }
  }
  _labelDrag = null;
}

function _setLabelEditMode(on) { _labelEditMode = !!on; }

// Her görünüm canvas'ına bir kez mousedown dinleyicisi (Yerleşim Modu drag).
_allViews.forEach(function(v) {
  v.canvas.addEventListener('mousedown', _onLabelMouseDown);
});

// setLayoutEditMode (LAF) çağrıldığında sprite sürükleme modunu da aç/kapa.
var _origSetLayoutEditMode = setLayoutEditMode;
setLayoutEditMode = function(enabled) {
  _origSetLayoutEditMode(enabled);
  _setLabelEditMode(enabled);
};

// ── Expose to Python via QWebChannel ──────────────────────────────
window.OrapsViewer = {
  loadModel: loadModel,
  setDoorState: setDoorState,
  applyDoorStates: applyDoorStates,
  resetDoors: resetDoors,
  setPortState: setPortState,
  applyPortStates: applyPortStates,
  resetPorts: resetPorts,
  setEnabledViews: setEnabledViews,  setPickMode: setPickMode,
  setRotateEnabled: setRotateEnabled,  viewFront: viewFront,
  viewTop: viewTop,
  viewIso: viewIso,
  viewReset: viewReset,
  setUnit: setUnit,
  setLafSensors: setLafSensors,
  updateLafValue: updateLafValue,
  setLayoutEditMode: setLayoutEditMode,
  setDoorNameLabels: setDoorNameLabels,
  setPortNameLabels: setPortNameLabels,
  setLabels3DVisible: setLabels3DVisible,
  setDoorLabels3DVisible: setDoorLabels3DVisible,
};

// Connect bridge (optional — viewer still works without Python)
if (typeof QWebChannel !== 'undefined' && typeof qt !== 'undefined' && qt.webChannelTransport) {
  new QWebChannel(qt.webChannelTransport, function(channel) {
    window._py_bridge = channel.objects.bridge;
    setStatus('Hazır');
    if (window._py_bridge && window._py_bridge.on_viewer_ready) {
      try { window._py_bridge.on_viewer_ready(); } catch (e) {}
    }
  });
} else {
  setStatus('Hazır (köprü yok)');
}

})();
