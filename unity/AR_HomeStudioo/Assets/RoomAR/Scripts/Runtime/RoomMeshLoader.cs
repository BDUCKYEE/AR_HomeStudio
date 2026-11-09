using System;
using System.IO;
using UnityEngine;
using UnityEngine.InputSystem;

namespace RoomAR
{
    /// <summary>
    /// 실행 중 SHARED_DIR/meshes/room_latest.glb를 불러와 MeshCollider를 붙입니다.
    ///  - 시작 시 자동 로드
    ///  - L 키: 최신 메시 다시 불러오기 (새 메시 로딩에 성공한 뒤에만 기존 메시를 교체)
    ///  - V 키: 메시 표시 켜기/끄기 (충돌은 유지)
    /// </summary>
    public class RoomMeshLoader : MonoBehaviour
    {
        [SerializeField] Material vertexColorMaterial;
        [SerializeField] bool loadOnStart = true;
        [Tooltip("비워 두면 .env의 SHARED_DIR/meshes/room_latest.glb")]
        [SerializeField] string overridePath = "";

        [Tooltip("메시 바닥에 구멍이 많을 때 공이 빠지지 않도록 y=0에 보이지 않는 바닥 충돌체를 둡니다 (규약: 바닥 높이 0). F 키로 토글.")]
        [SerializeField] bool safetyFloor = true;

        RoomMeshIO.LoadResult current;
        BoxCollider safetyFloorCol;
        bool loading;
        string status = "메시: 아직 불러오지 않음";
        DateTime loadedWriteTime;

        public RoomMeshIO.LoadResult Current => current;
        public string Status => status;

        string Path_ => string.IsNullOrEmpty(overridePath) ? RoomMeshIO.LatestGlbPath : overridePath;

        void OnEnable() => SandboxController.ExtraHelpLines.Add(HelpLine);
        void OnDisable() => SandboxController.ExtraHelpLines.Remove(HelpLine);

        string HelpLine() => $"L 메시 다시 불러오기 · V 메시 표시 · F 보조 바닥 ({(safetyFloor ? "켜짐" : "꺼짐")})\n{status}";

        void UpdateSafetyFloor()
        {
            if (safetyFloorCol == null)
            {
                var go = new GameObject("SafetyFloor (invisible, y=0)");
                go.transform.SetParent(transform, false);
                safetyFloorCol = go.AddComponent<BoxCollider>();
            }
            // 메시 수평 범위 + 여유 0.5m, 윗면이 y=0
            Bounds b = current != null ? current.Stats.WorldBounds : new Bounds(Vector3.zero, new Vector3(3.3f, 0f, 2.5f));
            const float t = 0.2f;
            safetyFloorCol.center = new Vector3(b.center.x, -t / 2f, b.center.z);
            safetyFloorCol.size = new Vector3(b.size.x + 1f, t, b.size.z + 1f);
            safetyFloorCol.enabled = safetyFloor;
        }

        void Start()
        {
            if (vertexColorMaterial == null)
            {
                var sh = Shader.Find("RoomAR/VertexColor");
                if (sh != null) vertexColorMaterial = new Material(sh);
            }
            UpdateSafetyFloor(); // 메시 로딩 전/실패 시에도 기본 크기 보조 바닥
            if (loadOnStart) Reload();
        }

        void Update()
        {
            var kb = Keyboard.current;
            if (kb == null) return;
            if (kb.lKey.wasPressedThisFrame) Reload();
            if (kb.fKey.wasPressedThisFrame) { safetyFloor = !safetyFloor; UpdateSafetyFloor(); }
            if (kb.vKey.wasPressedThisFrame && current?.Root != null)
                foreach (var r in current.Root.GetComponentsInChildren<Renderer>(true)) r.enabled = !r.enabled;
        }

        public async void Reload() => await ReloadAsync();

        public async System.Threading.Tasks.Task ReloadAsync()
        {
            if (loading) return;
            loading = true;
            string path = Path_;
            status = $"메시: 불러오는 중… {path}";
            var t0 = Time.realtimeSinceStartup;
            try
            {
                EnvConfig.Reload(); // .env 변경도 반영
                path = Path_;
                var res = await RoomMeshIO.LoadAsync(path, transform, vertexColorMaterial);
                if (this == null) { res.Dispose(); return; } // 로딩 중 씬 전환
                if (!res.Ok)
                {
                    status = $"메시: 실패 — {res.Error}" + (current != null ? " (이전 메시 유지)" : "");
                    Debug.LogWarning($"[RoomAR] {status}");
                    return;
                }
                current?.Dispose();
                current = res;
                UpdateSafetyFloor();
                loadedWriteTime = File.GetLastWriteTime(path);
                string sample = RoomMeshIO.IsSampleMesh(RoomMeshIO.ReadLatestJson()) ? " · 예제 이미지 메시" : "";
                status = $"메시: {Path.GetFileName(path)} ({loadedWriteTime:HH:mm:ss}){sample} · {Time.realtimeSinceStartup - t0:F1}s\n{res.Stats}";
                Debug.Log($"[RoomAR] {status}");
            }
            catch (Exception e)
            {
                status = $"메시: 예외 — {e.Message}";
                Debug.LogException(e);
            }
            finally { loading = false; }
        }

        void OnDestroy() => current?.Dispose();
    }
}
