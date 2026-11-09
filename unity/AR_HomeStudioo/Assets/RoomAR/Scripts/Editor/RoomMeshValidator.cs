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
