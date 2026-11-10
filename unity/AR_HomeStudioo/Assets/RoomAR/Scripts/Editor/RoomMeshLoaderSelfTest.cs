using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace RoomAR.EditorTools
{
    /// <summary>
    /// RoomMesh 씬의 RoomMeshLoader를 그대로 호출해 room_latest.glb를 불러오고(보조 바닥 포함),
    /// 메시 범위 9×9 격자에서 공을 떨어뜨려 빠지는지 확인합니다.
    ///   -executeMethod RoomAR.EditorTools.RoomMeshLoaderSelfTest.RunBatch  (-quit 없이)
    /// 종료 코드: 0 PASS, 1 FAIL, 2 로딩 실패.
    /// </summary>
    public static class RoomMeshLoaderSelfTest
    {
        public static void RunBatch()
        {
            var task = RunAsync();
            double start = EditorApplication.timeSinceStartup;
            EditorApplication.CallbackFunction poll = null;
            poll = () =>
            {
                if (!task.IsCompleted && EditorApplication.timeSinceStartup - start < 300) return;
                EditorApplication.update -= poll;
                int code = task.IsCompletedSuccessfully ? task.Result : 2;
                if (!task.IsCompletedSuccessfully) Debug.LogError($"[RoomAR][LoaderTest] 예외/시간 초과: {task.Exception}");
                Debug.Log($"[RoomAR][LoaderTest] exit {code}");
                EditorApplication.Exit(code);
            };
            EditorApplication.update += poll;
        }

        static async Task<int> RunAsync()
        {
            EditorSceneManager.OpenScene(SceneBuilder.RoomMeshScenePath, OpenSceneMode.Single);
            var loader = Object.FindFirstObjectByType<RoomAR.RoomMeshLoader>();
            if (loader == null) { Debug.LogError("[RoomAR][LoaderTest] RoomMeshLoader 없음"); return 2; }

            // -roomGlb <path> 로 다른 glb 지정 가능 (옆의 같은 이름 .json도 함께 읽음)
            var args = System.Environment.GetCommandLineArgs();
            int ai = System.Array.IndexOf(args, "-roomGlb");
            if (ai >= 0 && ai + 1 < args.Length)
            {
                var lso = new SerializedObject(loader);
                lso.FindProperty("overridePath").stringValue = args[ai + 1];
                lso.ApplyModifiedPropertiesWithoutUndo();
            }

            await loader.ReloadAsync();
            Debug.Log($"[RoomAR][LoaderTest] status: {loader.Status}");
            if (loader.Current == null || !loader.Current.Ok) return 2;

            // 보드 표시: json에 board_center_height_m가 있으면 (0, h, ~0)에 있어야 함
            bool boardOk = true;
            var marker = loader.GetComponent<RoomAR.BoardMarker>();
            float? bh = loader.Info?.BoardCenterHeightM;
            if (bh != null)
            {
                var paper = marker != null && marker.Root != null ? marker.Root.Find("Paper") : null;
                var r = paper != null ? paper.GetComponent<Renderer>() : null;
                boardOk = r != null && Vector3.Distance(r.bounds.center, new Vector3(0f, bh.Value, 0f)) < 0.02f
                          && paper.GetComponent<Collider>() == null;
                Debug.Log($"[RoomAR][LoaderTest] board: h={bh:F3}, paper center={(r != null ? r.bounds.center.ToString("F3") : "없음")}, size={(r != null ? r.bounds.size.ToString("F3") : "-")}, {marker?.Summary} → {(boardOk ? "OK" : "FAIL")}");
            }
            else Debug.Log($"[RoomAR][LoaderTest] board: 없음 ({marker?.Summary})");

            var camPos = Camera.main != null ? Camera.main.transform.position : Vector3.negativeInfinity;
            var cb = loader.Current.Stats.WorldBounds;
            bool camOk = camPos.x > cb.min.x && camPos.x < cb.max.x && camPos.z > cb.min.z && camPos.z < cb.max.z;
            Debug.Log($"[RoomAR][LoaderTest] camera {camPos:F2} forward {Camera.main?.transform.forward:F2} → 방 안 {(camOk ? "OK" : "FAIL")}");

            var root = loader.Current.Root;
            var mr = root.GetComponentInChildren<MeshRenderer>();
            bool matOk = mr != null && mr.sharedMaterial != null && mr.sharedMaterial.shader.name == "RoomAR/VertexColor";
            int colliders = root.GetComponentsInChildren<MeshCollider>().Length;
            Debug.Log($"[RoomAR][LoaderTest] material={mr?.sharedMaterial?.shader.name}, MeshCollider={colliders}");

            var b = loader.Current.Stats.WorldBounds;
            var prevMode = Physics.simulationMode;
            Physics.simulationMode = SimulationMode.Script;
            Physics.SyncTransforms();
            var balls = new List<Rigidbody>();
            for (int i = 0; i < 9; i++)
            for (int k = 0; k < 9; k++)
            {
                var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                go.transform.position = new Vector3(Mathf.Lerp(b.min.x, b.max.x, 0.1f + 0.8f * i / 8f), 1.2f,
                                                    Mathf.Lerp(b.min.z, b.max.z, 0.1f + 0.8f * k / 8f));
                go.transform.localScale = Vector3.one * 0.2f;
                var rb = go.AddComponent<Rigidbody>();
                rb.collisionDetectionMode = CollisionDetectionMode.ContinuousSpeculative;
                balls.Add(rb);
            }
            var starts = balls.Select(r => r.position).ToArray();
            var startOverlap = balls.Select(r => Physics.OverlapSphere(r.position, 0.1f).Count(c => c.attachedRigidbody == null)).ToArray();
            // 처음 y < -0.2가 된 순간의 XZ로 분류: 보조 바닥 범위(메시 범위 + 0.5m) 안이면 뚫림, 밖이면 벽 구멍으로 탈출
            var crossed = new Vector3?[balls.Count];
            for (int n = 0; n < 150; n++)
            {
                Physics.Simulate(0.02f);
                for (int i = 0; i < balls.Count; i++)
                    if (crossed[i] == null && balls[i].position.y < -0.2f) crossed[i] = balls[i].position;
            }
            int tunneled = 0, escaped = 0;
            for (int i = 0; i < balls.Count; i++)
            {
                if (crossed[i] == null) continue;
                var p = crossed[i].Value;
                bool inside = p.x > b.min.x - 0.5f && p.x < b.max.x + 0.5f && p.z > b.min.z - 0.5f && p.z < b.max.z + 0.5f;
                if (inside) tunneled++; else escaped++;
                Debug.Log($"[RoomAR][LoaderTest] {(inside ? "뚫림" : "탈출")}: start {starts[i]} (겹침 {startOverlap[i]}) → y=-0.2 통과 위치 {p}");
            }
            int fell = tunneled;
            Debug.Log($"[RoomAR][LoaderTest] 벽 구멍으로 방 밖 탈출 {escaped}개 (메시 품질 문제, 경고)");
            Physics.simulationMode = prevMode;
            Debug.Log($"[RoomAR][LoaderTest] 보조 바닥 켜짐: {balls.Count}개 중 바닥 뚫림 {fell}개");

            bool ok = matOk && colliders > 0 && fell == 0 && boardOk && camOk;
            Debug.Log(ok ? "[RoomAR][LoaderTest] PASS" : "[RoomAR][LoaderTest] FAIL");
            EditorSceneManager.OpenScene(SceneBuilder.RoomMeshScenePath, OpenSceneMode.Single); // 저장하지 않고 버림
            return ok ? 0 : 1;
        }
    }
}
