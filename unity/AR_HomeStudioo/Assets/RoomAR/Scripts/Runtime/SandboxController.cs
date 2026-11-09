using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.SceneManagement;

namespace RoomAR
{
    /// <summary>
    /// 물리 샌드박스 조작.
    ///  - Space: 카메라 앞에 공 생성
    ///  - 왼쪽 클릭: 클릭 위치로 Raycast, 맞은 Rigidbody에 힘(AddForceAtPosition)
    ///  - [ / ]: 공 탄성(bounciness) 감소/증가 (PhysicsMaterial)
    ///  - C: 공 모두 제거, R: 씬 초기화
    /// 조작법은 화면 왼쪽 위에 표시합니다.
    /// </summary>
    public class SandboxController : MonoBehaviour
    {
        [Header("Ball")]
        [SerializeField] PhysicsMaterial ballPhysicsMaterial;
        [SerializeField] Material ballMaterial;
        [SerializeField] float ballRadius = 0.1f;   // m
        [SerializeField] float ballMass = 0.3f;     // kg
        [SerializeField] float spawnDistance = 0.6f;
        [SerializeField] int maxBalls = 200;

        [Header("Force")]
        [SerializeField] float clickImpulse = 2.0f; // N·s
        [SerializeField] float rayDistance = 50f;

        [Header("Misc")]
        [SerializeField] float killHeight = -5f;
        [SerializeField] Camera cam;

        /// <summary>안내 텍스트에 덧붙일 추가 줄 (예: 메시 로더 상태).</summary>
        public static readonly List<System.Func<string>> ExtraHelpLines = new();

        readonly List<Rigidbody> balls = new();
        PhysicsMaterial runtimeMaterial; // 에셋을 직접 바꾸지 않도록 복제본 사용
        string lastHit = "-";
        GUIStyle style;

        public float Bounciness => runtimeMaterial != null ? runtimeMaterial.bounciness : 0f;

        void Awake()
        {
            if (cam == null) cam = Camera.main;
            runtimeMaterial = ballPhysicsMaterial != null
                ? Instantiate(ballPhysicsMaterial)
                : new PhysicsMaterial("BallRuntime") { bounciness = 0.8f, bounceCombine = PhysicsMaterialCombine.Maximum };
            runtimeMaterial.name = "BallRuntime";
        }

        void Update()
        {
            var kb = Keyboard.current;
            var mouse = Mouse.current;
            if (kb == null || mouse == null) return;

            if (kb.spaceKey.wasPressedThisFrame) SpawnBall();
            if (kb.cKey.wasPressedThisFrame) ClearBalls();
            if (kb.rKey.wasPressedThisFrame)
            {
                // 씬은 SceneBuilder가 Build Settings에 등록합니다.
                var scene = SceneManager.GetActiveScene();
                if (scene.buildIndex >= 0) SceneManager.LoadScene(scene.buildIndex);
                else SceneManager.LoadScene(scene.name);
                return;
            }
            if (kb.leftBracketKey.wasPressedThisFrame) SetBounciness(runtimeMaterial.bounciness - 0.1f);
            if (kb.rightBracketKey.wasPressedThisFrame) SetBounciness(runtimeMaterial.bounciness + 0.1f);

            if (mouse.leftButton.wasPressedThisFrame) PushAtCursor(mouse.position.ReadValue());

            // 방 밖으로 빠진 공 정리
            for (int i = balls.Count - 1; i >= 0; i--)
            {
                if (balls[i] == null) { balls.RemoveAt(i); continue; }
                if (balls[i].position.y < killHeight)
                {
                    Destroy(balls[i].gameObject);
                    balls.RemoveAt(i);
                }
            }
        }

        public Rigidbody SpawnBall()
        {
            if (cam == null) return null;
            if (balls.Count >= maxBalls)
            {
                if (balls[0] != null) Destroy(balls[0].gameObject);
                balls.RemoveAt(0);
            }

            var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            go.name = "Ball";
            go.transform.localScale = Vector3.one * ballRadius * 2f;
            go.transform.position = cam.transform.position + cam.transform.forward * spawnDistance;

            var col = go.GetComponent<SphereCollider>();
            col.sharedMaterial = runtimeMaterial;
            if (ballMaterial != null) go.GetComponent<MeshRenderer>().sharedMaterial = ballMaterial;

            var rb = go.AddComponent<Rigidbody>();
            rb.mass = ballMass;
            rb.interpolation = RigidbodyInterpolation.Interpolate;
            rb.collisionDetectionMode = CollisionDetectionMode.ContinuousSpeculative;
            rb.linearVelocity = cam.transform.forward * 1.0f;

            balls.Add(rb);
            return rb;
        }

        void PushAtCursor(Vector2 screenPos)
        {
            if (cam == null) return;
            Ray ray = cam.ScreenPointToRay(screenPos);
            if (Physics.Raycast(ray, out RaycastHit hit, rayDistance, ~0, QueryTriggerInteraction.Ignore))
            {
                lastHit = $"{hit.collider.name} @ {hit.point.x:F2}, {hit.point.y:F2}, {hit.point.z:F2}";
                if (hit.rigidbody != null && !hit.rigidbody.isKinematic)
                {
                    hit.rigidbody.AddForceAtPosition(ray.direction * clickImpulse, hit.point, ForceMode.Impulse);
                }
            }
            else
            {
                lastHit = "(없음)";
            }
        }

        void SetBounciness(float v)
        {
            // 런타임 복제본 하나를 모든 공이 공유하므로 기존 공에도 바로 반영됩니다.
            runtimeMaterial.bounciness = Mathf.Clamp01(Mathf.Round(v * 10f) / 10f);
        }

        void ClearBalls()
        {
            foreach (var b in balls) if (b != null) Destroy(b.gameObject);
            balls.Clear();
        }

        void OnGUI()
        {
            style ??= new GUIStyle(GUI.skin.box)
            {
                alignment = TextAnchor.UpperLeft,
                fontSize = 14,
                richText = true,
                padding = new RectOffset(10, 10, 8, 8),
            };
            if (style.font == null)
            {
                // 한글 표시용 OS 폰트 (없으면 기본 폰트 유지)
                var f = Font.CreateDynamicFontFromOSFont(new[] { "Malgun Gothic", "맑은 고딕", "Arial" }, 14);
                if (f != null) style.font = f;
            }

            var sb = new System.Text.StringBuilder();
            sb.AppendLine("<b>RoomAR 샌드박스</b>");
            sb.AppendLine("WASD 이동 · Q/E 하강/상승 · Shift 가속");
            sb.AppendLine("마우스 오른쪽 드래그: 시점");
            sb.AppendLine("Space 공 생성 · 왼쪽 클릭 힘 가하기");
            sb.AppendLine("[ / ] 탄성 조절 · C 공 제거 · R 초기화");
            foreach (var f in ExtraHelpLines)
            {
                string line = f?.Invoke();
                if (!string.IsNullOrEmpty(line)) sb.AppendLine(line);
            }
            sb.AppendLine($"공 {balls.Count}개 · 탄성 {Bounciness:F1}");
            sb.Append($"마지막 클릭: {lastHit}");

            var content = new GUIContent(sb.ToString());
            Vector2 size = style.CalcSize(content);
            GUI.Box(new Rect(10, 10, size.x, size.y), content, style);
        }
    }
}
