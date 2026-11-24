using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.InputSystem;

namespace RoomAR
{
    public enum CollisionMode { Original = 1, Smooth = 2, PlaneProxy = 3, Gs2d = 4, SpatialLm = 5 }

    /// <summary>
    /// 방 충돌 방식 전환. 보이는 메시는 항상 원본(RoomMeshLoader가 불러온 room_latest.glb)이고 충돌체만 바뀝니다.
    ///   1 원본 메시 · 2 스무딩 메시 · 3 평면+상자 프록시 · 4 2DGS 메시 · 5 SpatialLM 프록시
    ///   G: 현재 충돌체 미리보기 (V로 원본 메시를 숨기고 보면 편함)
    /// 실험 결과는 ${SHARED_DIR}/meshes/experiments/ 아래에서 모드별 이름 규칙(Specs)에 맞는 가장 최근 파일을 씁니다.
    /// 좌표: 모든 실험 결과는 원본과 같은 월드 좌표계(glTF). glb는 glTFast가, proxy.json은 RoomProxy가 Unity로 변환.
    /// </summary>
    [RequireComponent(typeof(RoomMeshLoader))]
    public class CollisionModeSwitcher : MonoBehaviour
    {
        public class Spec
        {
            public CollisionMode Mode;
            public string Name, Ext;
            public string[] Include, Exclude;
        }

        /// <summary>experiments/ 기준 상대 경로(소문자)에 Include 중 하나가 있고 Exclude가 없는 파일.
        /// 여러 개면 원본 메시 이름 폴더 → 이름이 proxy.json(json) → 가장 최근 순.</summary>
        public static readonly Spec[] Specs =
        {
            new() { Mode = CollisionMode.Original,   Name = "원본 메시" },
            new() { Mode = CollisionMode.Smooth,     Name = "스무딩 메시",       Ext = ".glb",  Include = new[] { "smooth" },             Exclude = new[] { "2dgs", "spatiallm" } },
            new() { Mode = CollisionMode.PlaneProxy, Name = "평면+상자 프록시",  Ext = ".json", Include = new[] { "proxy", "plane" },     Exclude = new[] { "spatiallm" } },
            new() { Mode = CollisionMode.Gs2d,       Name = "2DGS 메시",         Ext = ".glb",  Include = new[] { "2dgs" },               Exclude = new[] { "spatiallm" } },
            new() { Mode = CollisionMode.SpatialLm,  Name = "SpatialLM 프록시",  Ext = ".json", Include = new[] { "spatiallm" },          Exclude = Array.Empty<string>() },
        };

        public static Spec SpecOf(CollisionMode m) => Specs.First(s => s.Mode == m);

        [Tooltip("비워 두면 ${SHARED_DIR}/meshes/experiments")]
        [SerializeField] string experimentsDirOverride = "";

        [Tooltip("원본 메시를 처음 불러온 뒤 쓸 충돌 방식 (사용자 결정 2026-11-24: 충돌은 평면+상자 프록시, 화면은 원본). 파일이 없으면 원본 유지")]
        [SerializeField] CollisionMode defaultMode = CollisionMode.PlaneProxy;
        public CollisionMode DefaultMode => defaultMode;

        class Entry
        {
            public string Path;
            public DateTime WriteTime;
            public GameObject Root;               // 충돌체 묶음
            public RoomMeshIO.LoadResult Mesh;    // glb일 때
            public string Info;
            public void Dispose()
            {
                Mesh?.Dispose();
                if (Root != null) { if (Application.isPlaying) Destroy(Root); else DestroyImmediate(Root); }
                Mesh = null; Root = null;
            }
        }

        readonly Dictionary<CollisionMode, Entry> entries = new();
        RoomMeshLoader loader;
        Material previewMaterial;
        bool busy;

        public CollisionMode Mode { get; private set; } = CollisionMode.Original;
        public bool Preview { get; private set; }
        public string Status { get; private set; } = "충돌: 1 원본 메시";

        public string ExperimentsDir
        {
            get
            {
                if (!string.IsNullOrEmpty(experimentsDirOverride)) return experimentsDirOverride;
                var m = EnvConfig.MeshesDir;
                return m == null ? null : Path.Combine(m, "experiments");
            }
            set => experimentsDirOverride = value;
        }

        RoomMeshLoader Loader => loader != null ? loader : loader = GetComponent<RoomMeshLoader>();

        void OnEnable() => SandboxController.ExtraHelpLines.Add(HelpLine);
        void OnDisable() => SandboxController.ExtraHelpLines.Remove(HelpLine);
        void OnDestroy() { foreach (var e in entries.Values) e.Dispose(); entries.Clear(); }

        string HelpLine() => "1 원본 · 2 스무딩 · 3 평면+상자 · 4 2DGS · 5 SpatialLM (충돌만 바뀜) · G 충돌체 보기\n" + Status;

        void Update()
        {
            var kb = Keyboard.current;
            if (kb == null) return;
            for (int i = 1; i <= 5; i++)
            {
                var key = (Key)((int)Key.Digit1 + i - 1);
                var np = (Key)((int)Key.Numpad1 + i - 1);
                if (kb[key].wasPressedThisFrame || kb[np].wasPressedThisFrame) _ = SetModeAsync((CollisionMode)i);
            }
            if (kb.gKey.wasPressedThisFrame) SetPreview(!Preview);
        }

        /// <summary>모드에 맞는 파일 (없으면 null). Original은 원본 메시 경로.</summary>
        public string FindFile(CollisionMode mode)
        {
            var spec = SpecOf(mode);
            if (mode == CollisionMode.Original) return null;
            string dir = ExperimentsDir;
            if (string.IsNullOrEmpty(dir) || !Directory.Exists(dir)) return null;
            // interfaces.md 2절: experiments/<방법>/<원본 메시 이름>/... → 지금 보이는 원본 메시의 폴더를 우선
            string stem = Loader?.Info?.File != null ? Path.GetFileNameWithoutExtension(Loader.Info.File).ToLowerInvariant() : null;
            try
            {
                return Directory.EnumerateFiles(dir, "*" + spec.Ext, SearchOption.AllDirectories)
                    .Where(p =>
                    {
                        string rel = p.Substring(dir.Length).Replace('\\', '/').ToLowerInvariant();
                        if (rel.Contains("/.") || rel.EndsWith(".tmp" + spec.Ext)) return false; // 숨김/임시 파일 제외
                        if (rel.Contains("/archive/")) return false;
                        return spec.Include.Any(rel.Contains) && !spec.Exclude.Any(rel.Contains);
                    })
                    // 우선순위: 같은 원본 메시 폴더 → (json) 이름이 정확히 proxy.json → 가장 최근
                    .OrderByDescending(p => stem != null && p.Replace('\\', '/').ToLowerInvariant().Contains("/" + stem + "/"))
                    .ThenByDescending(p => spec.Ext != ".json" || Path.GetFileName(p).Equals("proxy.json", StringComparison.OrdinalIgnoreCase))
                    .ThenByDescending(File.GetLastWriteTimeUtc)
                    .FirstOrDefault();
            }
            catch (Exception e) { Debug.LogWarning($"[RoomAR] experiments 검색 실패: {e.Message}"); return null; }
        }

        /// <summary>충돌 방식을 바꿉니다. 해당 파일이 없거나 실패하면 이전 방식을 유지하고 false.</summary>
        public async Task<bool> SetModeAsync(CollisionMode mode)
        {
            if (busy) return false;
            busy = true;
            var spec = SpecOf(mode);
            try
            {
                if (mode != CollisionMode.Original)
                {
                    Status = $"충돌: {(int)mode} {spec.Name} 불러오는 중…";
                    var err = await EnsureLoaded(mode);
                    if (this == null) return false;
                    if (err != null)
                    {
                        Status = $"충돌: {(int)Mode} {SpecOf(Mode).Name} 유지 — {(int)mode} {spec.Name}: {err}";
                        Debug.LogWarning($"[RoomAR] {Status}");
                        return false;
                    }
                }
                Mode = mode;
                Apply();
                string info = mode == CollisionMode.Original ? OriginalInfo() : entries[mode].Info;
                Status = $"충돌: {(int)mode} {spec.Name} · {info}";
                Debug.Log($"[RoomAR] {Status}");
                return true;
            }
            catch (Exception e)
            {
                Status = $"충돌: {(int)mode} {spec.Name} 예외 — {e.Message}";
                Debug.LogException(e);
                return false;
            }
            finally { busy = false; }
        }

        string OriginalInfo()
        {
            var c = Loader != null ? Loader.Current : null;
            return c?.Root == null ? "원본 메시 없음" : $"MeshCollider {c.Root.GetComponentsInChildren<MeshCollider>(true).Length}개 · 삼각형 {c.Stats.TriangleCount:N0}";
        }

        async Task<string> EnsureLoaded(CollisionMode mode)
        {
            string path = FindFile(mode);
            if (path == null) return $"파일 없음 ({ExperimentsDir ?? "SHARED_DIR 미설정"})";
            var wt = File.GetLastWriteTime(path);
            if (entries.TryGetValue(mode, out var old) && old.Path == path && old.WriteTime == wt && old.Root != null) return null;

            var e = new Entry { Path = path, WriteTime = wt };
            var t0 = Time.realtimeSinceStartup;
            if (SpecOf(mode).Ext == ".glb")
            {
                var res = await RoomMeshIO.LoadAsync(path, transform, Loader != null ? Loader.VertexColorMaterial : null, addColliders: true);
                if (this == null) { res.Dispose(); return "중단"; }
                if (!res.Ok) return res.Error;
                res.Root.name = $"Collision {(int)mode} ({Path.GetFileName(path)})";
                foreach (var r in res.Root.GetComponentsInChildren<Renderer>(true)) r.enabled = false; // 보이는 메시는 원본만
                e.Mesh = res;
                e.Root = res.Root;
                e.Info = $"{Path.GetFileName(path)} · MeshCollider {res.Root.GetComponentsInChildren<MeshCollider>(true).Length}개 · 삼각형 {res.Stats.TriangleCount:N0}";
            }
            else
            {
                string json;
                using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                using (var sr = new StreamReader(fs)) json = await sr.ReadToEndAsync();
                if (this == null) return "중단";
                var room = Loader != null && Loader.Current != null ? Loader.Current.Stats.WorldBounds
                                                                     : new Bounds(new Vector3(0, 1.2f, 1.25f), new Vector3(3.3f, 2.4f, 2.5f));
                RoomProxy.Result pr;
                try { pr = RoomProxy.Parse(json, room); }
                catch (Exception ex) { return $"proxy 파싱 실패: {ex.Message}"; }
                if (pr.Shapes.Count == 0) return $"충돌체 0개 ({string.Join("; ", pr.Warnings)})";
                foreach (var w in pr.Warnings) Debug.LogWarning($"[RoomAR] {Path.GetFileName(path)}: {w}");
                e.Root = RoomProxy.Build(pr, transform, $"Collision {(int)mode} ({Path.GetFileName(path)})", PreviewMaterial());
                e.Info = $"{Path.GetFileName(path)} · {pr.Summary}";
            }
            e.Info += $" · {Time.realtimeSinceStartup - t0:F1}s";
            old?.Dispose();
            entries[mode] = e;
            return null;
        }

        Material PreviewMaterial()
        {
            if (previewMaterial == null)
            {
                var sh = Shader.Find("Universal Render Pipeline/Unlit");
                if (sh != null) previewMaterial = new Material(sh) { name = "CollisionPreview" };
            }
            return previewMaterial;
        }

        /// <summary>현재 모드의 충돌체만 켭니다. 원본 메시를 다시 불러온 뒤에도 호출됩니다.</summary>
        public void Apply()
        {
            var cur = Loader != null ? Loader.Current : null;
            if (cur?.Root != null)
                foreach (var c in cur.Root.GetComponentsInChildren<Collider>(true)) c.enabled = Mode == CollisionMode.Original;
            foreach (var kv in entries)
                if (kv.Value.Root != null) kv.Value.Root.SetActive(kv.Key == Mode);
            SetPreview(Preview);
        }

        public void SetPreview(bool on)
        {
            Preview = on;
            foreach (var kv in entries)
                if (kv.Value.Root != null)
                    foreach (var r in kv.Value.Root.GetComponentsInChildren<Renderer>(true)) r.enabled = on && kv.Key == Mode;
        }

        /// <summary>해당 모드의 충돌체 (검사용). Original이면 원본 메시의 MeshCollider.</summary>
        public List<Collider> CollidersOf(CollisionMode mode)
        {
            if (mode == CollisionMode.Original)
            {
                var cur = Loader != null ? Loader.Current : null;
                return cur?.Root == null ? new List<Collider>() : cur.Root.GetComponentsInChildren<Collider>(true).ToList();
            }
            return entries.TryGetValue(mode, out var e) && e.Root != null ? e.Root.GetComponentsInChildren<Collider>(true).ToList() : new List<Collider>();
        }

        public string InfoOf(CollisionMode mode) => mode == CollisionMode.Original ? OriginalInfo() : entries.TryGetValue(mode, out var e) ? e.Info : null;
        public string PathOf(CollisionMode mode) => entries.TryGetValue(mode, out var e) ? e.Path : null;
    }
}
