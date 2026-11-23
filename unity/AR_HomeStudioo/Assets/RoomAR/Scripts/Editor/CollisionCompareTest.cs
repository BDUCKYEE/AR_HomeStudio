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
    /// 충돌 방식(1 원본 · 2 스무딩 · 3 평면+상자 · 4 2DGS · 5 SpatialLM)별 공 낙하/투척 비교.
    ///   -executeMethod RoomAR.EditorTools.CollisionCompareTest.RunBatch  (-quit 없이)
    ///   선택: -roomGlb &lt;원본 glb&gt;  -experimentsDir &lt;폴더&gt;
    /// 결과: Logs/collision_compare.md (표) · 종료 코드 0 완료, 2 원본 로딩 실패.
    ///
    /// 보이는 메시/방 범위 기준은 항상 원본. 보조 바닥(y=0)은 꺼서 충돌체 자체만 봅니다.
    ///  - 낙하: 원본 범위 10~90% 9×9 격자, 높이 1.2m에서 떨어뜨림 (81개)
    ///  - 투척: 범위 30/50/70% 3×3 지점, 높이 1.0m에서 수평 12방향 6m/s + 위 1m/s (108개)
    ///  - 분류(처음 일어난 것): y &lt; -0.2 이고 XZ가 원본 범위 안 → 바닥 관통 / XZ가 원본 범위 밖으로 0.05m 넘게 → 벽 이탈 /
    ///    y &gt; 천장 + 0.2 → 천장 이탈
    ///  - 정합: 방 안 27지점 × 26방향 광선을 원본 충돌체와 비교한 거리 차 (X축 반전 등 좌표 실수 확인용)
    /// 공끼리는 충돌하지 않게(전용 레이어) 해서 공 사이 간섭을 뺍니다.
    /// </summary>
    public static class CollisionCompareTest
    {
        const int BallLayer = 31;
        const float BallRadius = 0.1f;
        public const string ReportPath = "Logs/collision_compare.md";

        public static void RunBatch()
        {
            var task = RunAsync();
            double start = EditorApplication.timeSinceStartup;
            EditorApplication.CallbackFunction poll = null;
            poll = () =>
            {
                if (!task.IsCompleted && EditorApplication.timeSinceStartup - start < 900) return;
                EditorApplication.update -= poll;
                int code = task.IsCompletedSuccessfully ? task.Result : 2;
                if (!task.IsCompletedSuccessfully) Debug.LogError($"[RoomAR][Compare] 예외/시간 초과: {task.Exception}");
                Debug.Log($"[RoomAR][Compare] exit {code}");
                EditorApplication.Exit(code);
            };
            EditorApplication.update += poll;
        }

        [MenuItem("RoomAR/충돌 방식 비교 (공 낙하)")]
        static async void RunMenu()
        {
            if (EditorApplication.isPlaying) { Debug.LogWarning("Play 모드가 아닐 때 실행하세요."); return; }
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            int code = await RunAsync();
            EditorUtility.RevealInFinder(ReportPath);
            Debug.Log($"[RoomAR][Compare] 완료 ({code})");
        }

        static string Arg(string name)
        {
            var a = Environment.GetCommandLineArgs();
            int i = Array.IndexOf(a, name);
            return i >= 0 && i + 1 < a.Length ? a[i + 1] : null;
        }

        class Row
        {
            public CollisionMode Mode;
            public string File = "-", Info = "", Note = "";
            public bool Available;
            public int DropN, DropFloor, DropWall, DropCeil;
            public int ThrowN, ThrowFloor, ThrowWall, ThrowCeil, ThrowSkipped;
            public float HitRatio = float.NaN, MedErr = float.NaN, P90Err = float.NaN;
        }

        static async Task<int> RunAsync()
        {
            EditorSceneManager.OpenScene(SceneBuilder.RoomMeshScenePath, OpenSceneMode.Single);
            var loader = UnityEngine.Object.FindFirstObjectByType<RoomMeshLoader>();
            if (loader == null) { Debug.LogError("[RoomAR][Compare] RoomMeshLoader 없음"); return 2; }
            string roomGlb = Arg("-roomGlb");
            if (roomGlb != null)
            {
                var so = new SerializedObject(loader);
                so.FindProperty("overridePath").stringValue = roomGlb;
                so.ApplyModifiedPropertiesWithoutUndo();
            }
            await loader.ReloadAsync();
            Debug.Log($"[RoomAR][Compare] 원본: {loader.Status}");
            if (loader.Current == null || !loader.Current.Ok) return 2;
            loader.SafetyFloor = false;

            var sw = loader.GetComponent<CollisionModeSwitcher>();
            if (sw == null) sw = loader.gameObject.AddComponent<CollisionModeSwitcher>();
            string exp = Arg("-experimentsDir");
            if (exp != null) sw.ExperimentsDir = exp;
            Debug.Log($"[RoomAR][Compare] experiments: {sw.ExperimentsDir} (존재 {(sw.ExperimentsDir != null && Directory.Exists(sw.ExperimentsDir))})");

            PhysicsMaterial ballMat = null;
            var sandbox = UnityEngine.Object.FindFirstObjectByType<SandboxController>();
            if (sandbox != null) ballMat = new SerializedObject(sandbox).FindProperty("ballPhysicsMaterial").objectReferenceValue as PhysicsMaterial;

            var room = loader.Current.Stats.WorldBounds;
            var prevMode = Physics.simulationMode;
            bool prevIgnore = Physics.GetIgnoreLayerCollision(BallLayer, BallLayer);
            Physics.simulationMode = SimulationMode.Script;
            Physics.IgnoreLayerCollision(BallLayer, BallLayer, true);

            // 정합 기준: 원본 충돌체 광선 거리
            var rays = MakeRays(room);
            float[] origDist = null;
            var rows = new List<Row>();
            try
            {
                foreach (var spec in CollisionModeSwitcher.Specs)
                {
                    var row = new Row { Mode = spec.Mode };
                    rows.Add(row);
                    bool ok = await sw.SetModeAsync(spec.Mode);
                    if (!ok)
                    {
                        row.Note = sw.Status;
                        Debug.Log($"[RoomAR][Compare] {(int)spec.Mode} {spec.Name}: 건너뜀 — {sw.Status}");
                        continue;
                    }
                    row.Available = true;
                    row.File = spec.Mode == CollisionMode.Original ? Path.GetFileName(loader.Current.Root.name.Replace("RoomMesh (", "").TrimEnd(')'))
                                                                   : Path.GetFileName(sw.PathOf(spec.Mode));
                    row.Info = sw.InfoOf(spec.Mode);
                    Physics.SyncTransforms();

                    var cols = sw.CollidersOf(spec.Mode);
                    var dist = RayDistances(rays, cols);
                    if (spec.Mode == CollisionMode.Original) origDist = dist;
                    if (origDist != null) Compare(origDist, dist, row);

                    // 낙하
                    var drops = new List<(Vector3 p, Vector3 v)>();
                    for (int i = 0; i < 9; i++)
                    for (int k = 0; k < 9; k++)
                        drops.Add((new Vector3(Mathf.Lerp(room.min.x, room.max.x, 0.1f + 0.8f * i / 8f), Mathf.Min(1.2f, room.max.y - 0.3f),
                                               Mathf.Lerp(room.min.z, room.max.z, 0.1f + 0.8f * k / 8f)), Vector3.zero));
                    var d = Simulate(drops, room, ballMat, false, out _);
                    (row.DropN, row.DropFloor, row.DropWall, row.DropCeil) = (drops.Count, d.floor, d.wall, d.ceil);

                    // 투척
                    var throws = new List<(Vector3 p, Vector3 v)>();
                    foreach (float fx in new[] { 0.3f, 0.5f, 0.7f })
                    foreach (float fz in new[] { 0.3f, 0.5f, 0.7f })
                    for (int a = 0; a < 12; a++)
                    {
                        float ang = a * 30f * Mathf.Deg2Rad;
                        var dir = new Vector3(Mathf.Cos(ang), 0, Mathf.Sin(ang));
                        var p = new Vector3(Mathf.Lerp(room.min.x, room.max.x, fx), 1.0f, Mathf.Lerp(room.min.z, room.max.z, fz));
                        throws.Add((p, dir * 6f + Vector3.up));
                    }
                    var t = Simulate(throws, room, ballMat, true, out int skipped);
                    (row.ThrowN, row.ThrowFloor, row.ThrowWall, row.ThrowCeil, row.ThrowSkipped) = (throws.Count - skipped, t.floor, t.wall, t.ceil, skipped);

                    Debug.Log($"[RoomAR][Compare] {(int)spec.Mode} {spec.Name}: 낙하 {row.DropN}개 중 바닥 관통 {row.DropFloor} · 벽 이탈 {row.DropWall} · 천장 {row.DropCeil} / " +
                              $"투척 {row.ThrowN}개 중 바닥 관통 {row.ThrowFloor} · 벽 이탈 {row.ThrowWall} · 천장 {row.ThrowCeil} (시작점이 충돌체 안이라 제외 {skipped}) / " +
                              $"정합 광선 일치 {row.HitRatio:P0} · 거리 차 중앙값 {row.MedErr * 100:F1}cm · 90% {row.P90Err * 100:F1}cm · {row.Info}");
                }
            }
            finally
            {
                Physics.simulationMode = prevMode;
                Physics.IgnoreLayerCollision(BallLayer, BallLayer, prevIgnore);
            }

            WriteReport(rows, loader, sw, room);
            EditorSceneManager.OpenScene(SceneBuilder.RoomMeshScenePath, OpenSceneMode.Single); // 저장하지 않고 버림
            return 0;
        }

        static (int floor, int wall, int ceil) Simulate(List<(Vector3 p, Vector3 v)> starts, Bounds room, PhysicsMaterial mat, bool skipInside, out int skipped)
        {
            skipped = 0;
            var balls = new List<Rigidbody>();
            int mask = ~(1 << BallLayer);
            foreach (var (p, v) in starts)
            {
                // 투척 시작점이 가구 상자/메시 안이면 결과가 의미 없으므로 제외
                if (skipInside && Physics.CheckSphere(p, BallRadius, mask, QueryTriggerInteraction.Ignore)) { skipped++; continue; }
                var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                go.layer = BallLayer;
                go.name = $"start {p:F2} v {v:F1}";
                go.transform.position = p;
                go.transform.localScale = Vector3.one * BallRadius * 2f;
                if (mat != null) go.GetComponent<SphereCollider>().sharedMaterial = mat;
                var rb = go.AddComponent<Rigidbody>();
                rb.mass = 0.3f;
                rb.collisionDetectionMode = CollisionDetectionMode.ContinuousSpeculative;
                rb.linearVelocity = v;
                balls.Add(rb);
            }
            Physics.SyncTransforms();
            var state = new int[balls.Count]; // 0 안, 1 바닥, 2 벽, 3 천장
            for (int n = 0; n < 200; n++) // 4초
            {
                Physics.Simulate(0.02f);
                for (int i = 0; i < balls.Count; i++)
                {
                    if (state[i] != 0) continue;
                    var p = balls[i].position;
                    bool insideXZ = p.x > room.min.x - 0.05f && p.x < room.max.x + 0.05f && p.z > room.min.z - 0.05f && p.z < room.max.z + 0.05f;
                    if (!insideXZ) state[i] = 2;
                    else if (p.y < -0.2f) state[i] = 1;
                    else if (p.y > room.max.y + 0.2f) state[i] = 3;
                }
            }
            if (Environment.GetCommandLineArgs().Contains("-compareVerbose"))
                for (int i = 0; i < balls.Count; i++)
                    if (state[i] != 0)
                        Debug.Log($"[RoomAR][Compare]   {(state[i] == 1 ? "바닥 관통" : state[i] == 2 ? "벽 이탈" : "천장")}: {balls[i].gameObject.name} → {balls[i].position:F2}");
            foreach (var b in balls) UnityEngine.Object.DestroyImmediate(b.gameObject);
            return (state.Count(s => s == 1), state.Count(s => s == 2), state.Count(s => s == 3));
        }

        static List<Ray> MakeRays(Bounds room)
        {
            var dirs = new List<Vector3>();
            for (int x = -1; x <= 1; x++)
            for (int y = -1; y <= 1; y++)
            for (int z = -1; z <= 1; z++)
                if (x != 0 || y != 0 || z != 0) dirs.Add(new Vector3(x, y, z).normalized);
            var rays = new List<Ray>();
            foreach (float fx in new[] { 0.3f, 0.5f, 0.7f })
            foreach (float fz in new[] { 0.3f, 0.5f, 0.7f })
            foreach (float y in new[] { 0.5f, 1.2f, 1.9f })
            foreach (var d in dirs)
                rays.Add(new Ray(new Vector3(Mathf.Lerp(room.min.x, room.max.x, fx), Mathf.Min(y, room.max.y - 0.1f), Mathf.Lerp(room.min.z, room.max.z, fz)), d));
            return rays;
        }

        static float[] RayDistances(List<Ray> rays, List<Collider> cols)
        {
            var r = new float[rays.Count];
            for (int i = 0; i < rays.Count; i++)
            {
                float best = float.PositiveInfinity;
                foreach (var c in cols)
                    if (c != null && c.enabled && c.gameObject.activeInHierarchy && c.Raycast(rays[i], out var hit, 20f) && hit.distance < best) best = hit.distance;
                r[i] = best;
            }
            return r;
        }

        static void Compare(float[] orig, float[] mode, Row row)
        {
            var errs = new List<float>();
            int origHits = 0, both = 0;
            for (int i = 0; i < orig.Length; i++)
            {
                if (float.IsInfinity(orig[i])) continue;
                origHits++;
                if (float.IsInfinity(mode[i])) continue;
                both++;
                errs.Add(Mathf.Abs(orig[i] - mode[i]));
            }
            row.HitRatio = origHits > 0 ? (float)both / origHits : float.NaN;
            if (errs.Count == 0) return;
            errs.Sort();
            row.MedErr = errs[errs.Count / 2];
            row.P90Err = errs[Mathf.Min(errs.Count - 1, (int)(errs.Count * 0.9f))];
        }

        static void WriteReport(List<Row> rows, RoomMeshLoader loader, CollisionModeSwitcher sw, Bounds room)
        {
            var sb = new StringBuilder();
            sb.AppendLine($"# 충돌 방식 비교 ({DateTime.Now:yyyy-MM-dd HH:mm})");
            sb.AppendLine();
            sb.AppendLine($"- 원본(보이는 메시): `{loader.Current.Root.name}` · 범위 X {room.size.x:F2} × Y {room.size.y:F2} × Z {room.size.z:F2} m");
            sb.AppendLine($"- experiments: `{sw.ExperimentsDir}` · 보조 바닥 끔 · 공 반지름 {BallRadius}m, ContinuousSpeculative, 공끼리 충돌 없음");
            sb.AppendLine();
            sb.AppendLine("| 키 | 충돌 방식 | 파일 | 낙하: 바닥 관통 / 벽 이탈 | 투척: 바닥 관통 / 벽 이탈 / 천장 | 원본과 광선 일치 | 거리 차 중앙값 / 90% | 충돌체 |");
            sb.AppendLine("|---|---|---|---|---|---|---|---|");
            foreach (var r in rows)
            {
                var spec = CollisionModeSwitcher.SpecOf(r.Mode);
                if (!r.Available) { sb.AppendLine($"| {(int)r.Mode} | {spec.Name} | 없음 | - | - | - | - | - |"); continue; }
                string info = (r.Info ?? "").Replace("|", "/");
                string align = r.Mode == CollisionMode.Original ? "기준" : float.IsNaN(r.HitRatio) ? "-" : $"{r.HitRatio:P0}";
                string err = r.Mode == CollisionMode.Original ? "기준" : float.IsNaN(r.MedErr) ? "-" : $"{r.MedErr * 100:F1} / {r.P90Err * 100:F1} cm";
                sb.AppendLine($"| {(int)r.Mode} | {spec.Name} | `{r.File}` | {r.DropFloor} / {r.DropWall} (/{r.DropN}) | " +
                              $"{r.ThrowFloor} / {r.ThrowWall} / {r.ThrowCeil} (/{r.ThrowN}{(r.ThrowSkipped > 0 ? $", 제외 {r.ThrowSkipped}" : "")}) | {align} | {err} | {info} |");
            }
            File.WriteAllText(ReportPath, sb.ToString(), new UTF8Encoding(false));
            Debug.Log($"[RoomAR][Compare] 보고서 {Path.GetFullPath(ReportPath)}\n{sb}");
        }
    }
}
