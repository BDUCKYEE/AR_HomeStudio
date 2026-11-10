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

        [Tooltip("room_latest.json에 board_center_height_m가 있으면 벽 보드 위치를 얇은 사각형으로 표시. B 키로 토글.")]
        [SerializeField] BoardMarker boardMarker;

        RoomMeshIO.LoadResult current;
        BoxCollider safetyFloorCol;
        public RoomMeshInfo Info { get; private set; }
        bool loading;
        string status = "메시: 아직 불러오지 않음";
        DateTime loadedWriteTime;

        public RoomMeshIO.LoadResult Current => current;
        public string Status => status;

        string Path_ => string.IsNullOrEmpty(overridePath) ? RoomMeshIO.LatestGlbPath : overridePath;

        void OnEnable() => SandboxController.ExtraHelpLines.Add(HelpLine);
        void OnDisable() => SandboxController.ExtraHelpLines.Remove(HelpLine);

        string HelpLine() => $"L 메시 다시 불러오기 · V 메시 표시 · F 보조 바닥 ({(safetyFloor ? "켜짐" : "꺼짐")}) · B 보드 표시\n{status}" +
                             (boardMarker != null ? $"\n{boardMarker.Summary}" : "");

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

        /// <summary>
        /// 카메라가 메시 범위 밖이면 방 안쪽 끝(+Z 쪽, 벽에서 0.6m)·눈높이 1.5m에 두고 보드 벽(-Z)을 바라보게 합니다.
        /// (원점이 벽 보드 아래라 씬의 기본 카메라 z=-1은 벽 밖)
        /// </summary>
        public static void PlaceCameraInside(Bounds b)
        {
            var cam = Camera.main;
            if (cam == null) return;
            var p = cam.transform.position;
            bool inside = p.x > b.min.x && p.x < b.max.x && p.z > b.min.z && p.z < b.max.z && p.y > 0f && p.y < b.max.y;
            if (inside) return;
            float z = Mathf.Max(b.center.z, b.max.z - 0.6f);
            cam.transform.SetPositionAndRotation(new Vector3(b.center.x, Mathf.Min(1.5f, b.max.y - 0.2f), z),
                                                 Quaternion.LookRotation(new Vector3(0f, 0.9f, 0f) - new Vector3(b.center.x, 1.5f, z)));
            var fly = cam.GetComponent<FlyCamera>();
            if (fly != null) { fly.enabled = false; fly.enabled = true; } // yaw/pitch 재설정 (OnEnable)
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
            if (kb.bKey.wasPressedThisFrame && boardMarker != null) boardMarker.SetVisible(!boardMarker.Visible);
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
                bool first = current == null;
                current?.Dispose();
                current = res;
                UpdateSafetyFloor();
                if (first) PlaceCameraInside(res.Stats.WorldBounds);
                loadedWriteTime = File.GetLastWriteTime(path);
                Info = RoomMeshIO.ParseInfo(RoomMeshIO.ReadSiblingJson(path));
                if (boardMarker == null) boardMarker = GetComponent<BoardMarker>();
                if (boardMarker == null) boardMarker = gameObject.AddComponent<BoardMarker>();
                boardMarker.Apply(Info);
                string sample = Info.IsSample ? " · 예제 이미지 메시" : Info.Source == "real" ? " · 실제 방" : "";
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
