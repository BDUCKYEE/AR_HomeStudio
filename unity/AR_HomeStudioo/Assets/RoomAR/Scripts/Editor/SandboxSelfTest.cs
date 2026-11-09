using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace RoomAR.EditorTools
{
    /// <summary>
    /// 박스 방 물리 자가 테스트 (플레이 모드 없이 Physics.Simulate로 진행).
    ///   -executeMethod RoomAR.EditorTools.SandboxSelfTest.Run
    /// 검사: 공이 바닥에서 튀어 오르는지, 방 밖으로 빠지지 않는지, 클릭 Raycast + AddForce가 공을 움직이는지.
    /// 실패 시 배치 모드 종료 코드 1.
    /// </summary>
    public static class SandboxSelfTest
    {
        [MenuItem("RoomAR/Self Test Box Room Physics")]
        public static void Run()
        {
            EditorSceneManager.OpenScene(SceneBuilder.BoxRoomScenePath, OpenSceneMode.Single);
            var prevMode = Physics.simulationMode;
            Physics.simulationMode = SimulationMode.Script;
            bool ok = true;
            try
            {
                var pm = SceneBuilder.GetBallPhysicsMaterial();

                // 1) 낙하 → 반발
                var ball = MakeBall(new Vector3(0f, 1.5f, -0.6f), pm);
                float dt = Time.fixedDeltaTime;
                bool touched = false; float bounceTop = 0f; float minY = float.MaxValue;
                for (int i = 0; i < (int)(3f / dt); i++)
                {
                    Physics.Simulate(dt);
                    float y = ball.position.y;
                    minY = Mathf.Min(minY, y);
                    // 첫 반발: 낮은 위치에서 속도가 위쪽으로 바뀌는 순간 (speculative contact는 표면 약간 위에서 튕김)
                    if (!touched && y < 0.2f && ball.linearVelocity.y > 0.5f) touched = true;
                    if (touched) bounceTop = Mathf.Max(bounceTop, y);
                }
                Debug.Log($"[RoomAR][SelfTest] drop 1.5m: touched={touched}, bounce peak={bounceTop:F2}m, minY={minY:F3}m (bounciness={pm.bounciness:F1})");
                ok &= Check(touched && bounceTop > 0.5f, "공이 바닥에서 0.5m 이상 튀어 올라야 함");
                ok &= Check(minY > 0.09f, "공(반지름 0.1m)이 바닥에 1cm 넘게 파고들지 않아야 함");

                // 2) 벽을 향해 빠르게 던짐 → 방 안에 머무름
                var fast = MakeBall(new Vector3(0f, 1.0f, 0f), pm);
                fast.linearVelocity = new Vector3(15f, 2f, 9f);
                for (int i = 0; i < (int)(4f / dt); i++) Physics.Simulate(dt);
                Vector3 p = fast.position;
                bool inside = Mathf.Abs(p.x) < SceneBuilder.RoomX / 2f && Mathf.Abs(p.z) < SceneBuilder.RoomZ / 2f && p.y > 0f && p.y < SceneBuilder.RoomH;
                Debug.Log($"[RoomAR][SelfTest] fast throw final pos={p}");
                ok &= Check(inside, "빠르게 던진 공이 방 안에 있어야 함");

                // 3) Raycast + AddForceAtPosition (클릭과 같은 경로)
                var still = MakeBall(new Vector3(0f, 0.1f, 0.3f), pm);
                for (int i = 0; i < 100; i++) Physics.Simulate(dt); // 안정화
                var origin = still.position + new Vector3(0f, 0f, -1.0f);
                var ray = new Ray(origin, Vector3.forward);
                bool hit = Physics.Raycast(ray, out var h, 5f) && h.rigidbody == still;
                if (hit) h.rigidbody.AddForceAtPosition(ray.direction * 2f, h.point, ForceMode.Impulse);
                Physics.Simulate(dt);
                Debug.Log($"[RoomAR][SelfTest] raycast hit ball={hit}, velocity after impulse={still.linearVelocity}");
                ok &= Check(hit && still.linearVelocity.z > 1f, "Raycast로 맞힌 공이 힘을 받아 움직여야 함");
            }
            finally
            {
                Physics.simulationMode = prevMode;
                // 씬은 저장하지 않음 (테스트용 공 버림)
                EditorSceneManager.OpenScene(SceneBuilder.BoxRoomScenePath, OpenSceneMode.Single);
            }

            Debug.Log(ok ? "[RoomAR][SelfTest] PASS" : "[RoomAR][SelfTest] FAIL");
            if (Application.isBatchMode) EditorApplication.Exit(ok ? 0 : 1);
        }

        static Rigidbody MakeBall(Vector3 pos, PhysicsMaterial pm)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            go.transform.position = pos;
            go.transform.localScale = Vector3.one * 0.2f;
            go.GetComponent<SphereCollider>().sharedMaterial = pm;
            var rb = go.AddComponent<Rigidbody>();
            rb.mass = 0.3f;
            rb.collisionDetectionMode = CollisionDetectionMode.ContinuousSpeculative;
            return rb;
        }

        static bool Check(bool cond, string msg)
        {
            if (cond) Debug.Log($"[RoomAR][SelfTest] OK   {msg}");
            else Debug.LogError($"[RoomAR][SelfTest] FAIL {msg}");
            return cond;
        }
    }
}
