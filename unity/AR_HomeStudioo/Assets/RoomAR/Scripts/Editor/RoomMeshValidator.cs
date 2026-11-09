using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace RoomAR.EditorTools
{
    /// <summary>
    /// room_latest.glb 검증 (바운딩 박스, 바닥 높이, 삼각형 수, 정점 색).
    ///   메뉴: RoomAR > Validate room_latest.glb
    ///   배치: Unity.exe -batchmode -nographics -projectPath ... -executeMethod RoomAR.EditorTools.RoomMeshValidator.ValidateBatch
    ///         [-roomGlb &lt;path&gt;]   (-quit 없이 실행. 끝나면 스스로 종료)
    /// 종료 코드: 0 = OK/WARN, 1 = FAIL 항목 있음, 2 = 파일 없음/로딩 실패.
    /// 보고서: Logs/room_mesh_validation.md (git 제외)
    ///
    /// room_latest.json이 예제 이미지 메시라고 표시하면 크기 검사는 경고만 냅니다.
    /// </summary>
    public static class RoomMeshValidator
    {
        // 실측 방 (PROJECT_BRIEF): 3.3m × 2.5m, 높이 2.4m
        const float RoomLong = 3.3f, RoomShort = 2.5f, RoomH = 2.4f;
        const float SizeTol = 0.15f;             // ±15%
        const float FloorTol = 0.05f;            // 바닥 p1 |y| ≤ 5cm
        const long TriWarn = 500_000, TriFail = 1_000_000;

        public static string ReportPath => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "Logs", "room_mesh_validation.md"));

        enum Level { OK, WARN, FAIL }

        [MenuItem("RoomAR/Validate room_latest.glb")]
        public static async void ValidateMenu()
        {
            var (code, report) = await RunAsync(RoomMeshIO.LatestGlbPath);
            Debug.Log(report);
            EditorUtility.DisplayDialog("Room mesh validation", report.Length > 1500 ? report.Substring(0, 1500) : report, "OK");
        }

        public static void ValidateBatch()
        {
            string path = GetArg("-roomGlb") ?? RoomMeshIO.LatestGlbPath;
            Task<(int, string)> task = RunAsync(path);
            EditorApplication.CallbackFunction poll = null;
            double start = EditorApplication.timeSinceStartup;
            poll = () =>
            {
                if (!task.IsCompleted && EditorApplication.timeSinceStartup - start < 300) return;
                EditorApplication.update -= poll;
                int code = 2;
                if (task.IsCompletedSuccessfully) { code = task.Result.Item1; Debug.Log(task.Result.Item2); }
                else Debug.LogError($"[RoomAR][Validate] 시간 초과 또는 예외: {task.Exception}");
                Debug.Log($"[RoomAR][Validate] exit {code}");
                EditorApplication.Exit(code);
            };
            EditorApplication.update += poll;
        }

        static async Task<(int, string)> RunAsync(string glbPath)
        {
            var items = new List<(Level lv, string name, string detail)>();
            var sb = new StringBuilder();
            string jsonPath = glbPath == null ? null : Path.ChangeExtension(glbPath, ".json");
            string json = jsonPath != null && File.Exists(jsonPath) ? File.ReadAllText(jsonPath) : null;
            bool sample = RoomMeshIO.IsSampleMesh(json);

            sb.AppendLine($"# room mesh validation ({DateTime.Now:yyyy-MM-dd HH:mm})");
            sb.AppendLine($"- glb: `{glbPath}`");
            sb.AppendLine($"- json: {(json != null ? $"`{jsonPath}`" : "없음")}{(sample ? " → **예제 이미지 메시 (크기 검사는 경고만)**" : "")}");

            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var parent = new GameObject("ValidateRoot").transform;
            var t0 = DateTime.Now;
            var res = await RoomMeshIO.LoadAsync(glbPath, parent, null, addColliders: true);
            if (!res.Ok)
            {
                sb.AppendLine($"- **FAIL** 로딩: {res.Error}");
                Finish(sb);
                return (2, sb.ToString());
            }
            double loadSec = (DateTime.Now - t0).TotalSeconds;
            var s = res.Stats;
            var b = s.WorldBounds;

            // 삼각형 수
            Level triLv = s.TriangleCount == 0 || s.TriangleCount > TriFail ? Level.FAIL : s.TriangleCount > TriWarn ? Level.WARN : Level.OK;
            items.Add((triLv, "삼각형 수", $"{s.TriangleCount:N0} (경고 > {TriWarn:N0}, 실패 > {TriFail:N0})"));

            // 정점 색
            items.Add((s.HasVertexColors ? Level.OK : Level.WARN, "정점 색", s.HasVertexColors ? "COLOR_0 있음" : "없음 (회색으로 표시됨)"));

            // MeshCollider 생성
            int colliders = parent.GetComponentsInChildren<MeshCollider>(true).Count(c => c.sharedMesh != null);
            items.Add((colliders > 0 ? Level.OK : Level.FAIL, "MeshCollider", $"{colliders}개"));

            // 바운딩 박스 (Unity 좌표 = glTFast 변환 후). 수평 두 변은 방향을 모르므로 긴 변/짧은 변으로 비교
            float hLong = Mathf.Max(b.size.x, b.size.z), hShort = Mathf.Min(b.size.x, b.size.z);
            Level SizeLv(float v, float expect)
            {
                bool ok = Mathf.Abs(v - expect) <= expect * SizeTol;
                return ok ? Level.OK : sample ? Level.WARN : Level.FAIL;
            }
            items.Add((SizeLv(hLong, RoomLong), "수평 긴 변", $"{hLong:F2} m (기대 {RoomLong} ±{SizeTol:P0})"));
            items.Add((SizeLv(hShort, RoomShort), "수평 짧은 변", $"{hShort:F2} m (기대 {RoomShort} ±{SizeTol:P0})"));
            items.Add((SizeLv(b.size.y, RoomH), "높이", $"{b.size.y:F2} m (기대 {RoomH} ±{SizeTol:P0})"));
            items.Add((Level.OK, "바운딩 박스", $"min ({b.min.x:F2}, {b.min.y:F2}, {b.min.z:F2}) / max ({b.max.x:F2}, {b.max.y:F2}, {b.max.z:F2}) / center ({b.center.x:F2}, {b.center.y:F2}, {b.center.z:F2})"));

            // 바닥 높이: 정점 y 1% 분위수가 0 근처여야 함 (바닥 = 높이 0 규약)
            Level floorLv = Mathf.Abs(s.FloorP1) <= FloorTol ? Level.OK : Level.FAIL;
            items.Add((floorLv, "바닥 높이", $"p1 {s.FloorP1:F3} m, p5 {s.FloorP5:F3} m, min {b.min.y:F3} m, |y|<3cm 정점 {s.NearFloorRatio:P1} (기대 p1 |y| ≤ {FloorTol} m)"));

            // 원점이 방 안에 있는지 (ChArUco 보드가 바닥 위에 있으므로 수평 원점은 바운딩 박스 안이어야 함)
            bool originInside = b.min.x <= 0 && b.max.x >= 0 && b.min.z <= 0 && b.max.z >= 0;
            items.Add((originInside ? Level.OK : Level.WARN, "원점 위치", originInside ? "월드 원점(XZ)이 메시 범위 안" : "월드 원점(XZ)이 메시 범위 밖 — 원점 정렬 확인 필요"));

            // MeshCollider 동작: (1) 내부 80% 영역 9×9 격자에서 아래로 Raycast → 바닥(|y|<0.15m) 맞는 비율
            //                    (2) 같은 격자 중 바닥이 맞은 곳에 공을 1.2m에서 떨어뜨려 3초 뒤 메시 아래로 빠지지 않는지
            Physics.SyncTransforms();
            int rays = 0, floorHits = 0;
            var dropPoints = new List<Vector3>();
            for (int i = 0; i < 9; i++)
            for (int k = 0; k < 9; k++)
            {
                float x = Mathf.Lerp(b.min.x, b.max.x, 0.1f + 0.8f * i / 8f);
                float z = Mathf.Lerp(b.min.z, b.max.z, 0.1f + 0.8f * k / 8f);
                rays++;
                // 천장/가구에 막히지 않도록 바닥 바로 위(0.3m)에서 쏨
                if (Physics.Raycast(new Vector3(x, 0.3f, z), Vector3.down, out var hit, 1f) && Mathf.Abs(hit.point.y) < 0.15f)
                {
                    floorHits++;
                    dropPoints.Add(new Vector3(x, 1.2f, z));
                }
            }
            // 같은 격자를 뒷면 포함으로 다시 쏴서 법선(면 방향) 뒤집힘과 실제 구멍을 구분
            bool prevBack = Physics.queriesHitBackfaces;
            Physics.queriesHitBackfaces = true;
            int anyHits = 0;
            for (int i = 0; i < 9; i++)
            for (int k = 0; k < 9; k++)
            {
                float x = Mathf.Lerp(b.min.x, b.max.x, 0.1f + 0.8f * i / 8f);
                float z = Mathf.Lerp(b.min.z, b.max.z, 0.1f + 0.8f * k / 8f);
                if (Physics.Raycast(new Vector3(x, 0.3f, z), Vector3.down, out var hit, 1f) && Mathf.Abs(hit.point.y) < 0.15f) anyHits++;
            }
            Physics.queriesHitBackfaces = prevBack;

            float hitRatio = (float)floorHits / rays;
            items.Add((hitRatio >= 0.5f ? Level.OK : Level.WARN, "바닥 Raycast",
                $"앞면 {floorHits}/{rays} ({hitRatio:P0}), 뒷면 포함 {anyHits}/{rays} 지점에서 y≈0 바닥 충돌 " +
                (anyHits > floorHits * 2 ? "→ 바닥 면 방향(법선)이 아래를 향함" : "→ 차이 작음: 바닥 구멍/누락")));

            if (dropPoints.Count > 0)
            {
                var prevMode = Physics.simulationMode;
                Physics.simulationMode = SimulationMode.Script;
                var balls = new List<Rigidbody>();
                foreach (var p in dropPoints)
                {
                    var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                    go.transform.position = p;
                    go.transform.localScale = Vector3.one * 0.2f;
                    var rb = go.AddComponent<Rigidbody>();
                    rb.collisionDetectionMode = CollisionDetectionMode.ContinuousSpeculative;
                    balls.Add(rb);
                }
                for (int n = 0; n < 150; n++) Physics.Simulate(0.02f);
                int fell = balls.Count(r => r.position.y < -0.2f);
                foreach (var r in balls) UnityEngine.Object.DestroyImmediate(r.gameObject);
                Physics.simulationMode = prevMode;
                items.Add((fell == 0 ? Level.OK : fell <= balls.Count / 10 ? Level.WARN : Level.FAIL,
                    "공 낙하 테스트 (메시 단독)", $"바닥이 맞은 {balls.Count}지점 중 {fell}개가 y<-0.2로 빠짐 (1.2m 낙하, 3초, 보조 바닥 없이)"));
            }

            sb.AppendLine($"- 로딩 시간: {loadSec:F2}s, 메시 {s.MeshCount}개, 정점 {s.VertexCount:N0}");
            sb.AppendLine();
            sb.AppendLine("| 결과 | 항목 | 값 |");
            sb.AppendLine("|---|---|---|");
            foreach (var (lv, name, detail) in items) sb.AppendLine($"| {lv} | {name} | {detail} |");

            Level overall = items.Max(i => i.lv);
            sb.AppendLine();
            sb.AppendLine($"**종합: {overall}**");
            res.Dispose();
            Finish(sb);
            return (overall == Level.FAIL ? 1 : 0, sb.ToString());
        }

        static void Finish(StringBuilder sb)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(ReportPath));
                File.WriteAllText(ReportPath, sb.ToString(), new UTF8Encoding(false));
            }
            catch (Exception e) { Debug.LogWarning($"[RoomAR][Validate] 보고서 저장 실패: {e.Message}"); }
        }

        static string GetArg(string name)
        {
            var args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++) if (args[i] == name) return args[i + 1];
            return null;
        }
    }
}
