using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

namespace RoomAR.EditorTools
{
    /// <summary>
    /// 씬 자동 생성. 메뉴 RoomAR/... 또는 배치 모드
    ///   Unity.exe -batchmode -projectPath ... -executeMethod RoomAR.EditorTools.SceneBuilder.BuildAll -quit
    ///
    /// 좌표: Unity 월드 = 미터, Y 위. 박스 방은 바닥 중심을 원점(바닥 높이 0)에 둡니다.
    /// 방 크기 X 3.3m × Z 2.5m × 높이 2.4m (실측).
    /// </summary>
    public static class SceneBuilder
    {
        public const string Root = "Assets/RoomAR";
        public const string ScenesDir = Root + "/Scenes";
        public const string MaterialsDir = Root + "/Materials";
        public const string PhysicsDir = Root + "/Physics";
        public const string BoxRoomScenePath = ScenesDir + "/BoxRoom.unity";

        public const float RoomX = 3.3f;
        public const float RoomZ = 2.5f;
        public const float RoomH = 2.4f;
        const float WallT = 0.1f;

        public const string RoomMeshScenePath = ScenesDir + "/RoomMesh.unity";
        public const string VertexColorMatPath = MaterialsDir + "/RoomVertexColor.mat";

        [MenuItem("RoomAR/Build All Scenes")]
        public static void BuildAll()
        {
            BuildBoxRoomScene();
            BuildRoomMeshScene();
            RegisterBuildScenes(RoomMeshScenePath);
        }

        /// <summary>
        /// 방 메시 씬: 실행 시 SHARED_DIR/meshes/room_latest.glb를 불러옴 (L 키로 다시 불러오기).
        /// 메시가 없으면 빈 공간이므로 비상시에는 BoxRoom 씬을 사용합니다.
        /// </summary>
        [MenuItem("RoomAR/Build Room Mesh Scene")]
        public static void BuildRoomMeshScene()
        {
            EnsureFolders();
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            CreateLight();
            var cam = CreateCamera(new Vector3(0f, 1.6f, -1.0f), new Vector3(20f, 0f, 0f));
            CreateSandbox(cam);

            var loaderGo = new GameObject("RoomMeshLoader");
            var loader = loaderGo.AddComponent<RoomAR.RoomMeshLoader>();
            var so = new SerializedObject(loader);
            so.FindProperty("vertexColorMaterial").objectReferenceValue = GetVertexColorMaterial();
            so.ApplyModifiedPropertiesWithoutUndo();

            EditorSceneManager.SaveScene(scene, RoomMeshScenePath);
            Debug.Log($"[RoomAR] Built {RoomMeshScenePath}");
        }

        public static Material GetVertexColorMaterial()
        {
            var mat = AssetDatabase.LoadAssetAtPath<Material>(VertexColorMatPath);
            if (mat != null) return mat;
            var shader = Shader.Find("RoomAR/VertexColor");
            if (shader == null) throw new System.Exception("Shader RoomAR/VertexColor not found (Assets/RoomAR/Shaders/VertexColor.shader)");
            mat = new Material(shader) { name = "RoomVertexColor" };
            AssetDatabase.CreateAsset(mat, VertexColorMatPath);
            return mat;
        }

        [MenuItem("RoomAR/Build Box Room Scene (비상용)")]
        public static void BuildBoxRoomScene()
        {
            EnsureFolders();
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            CreateLight();
            var cam = CreateCamera(new Vector3(0f, 1.6f, -RoomZ / 2f + 0.3f), new Vector3(20f, 0f, 0f));
            CreateBoxRoom();
            CreateSandbox(cam);

            EditorSceneManager.SaveScene(scene, BoxRoomScenePath);
            Debug.Log($"[RoomAR] Built {BoxRoomScenePath}");
        }

        // ---------- 공용 구성 요소 ----------

        public static void EnsureFolders()
        {
            foreach (var dir in new[] { Root, ScenesDir, MaterialsDir, PhysicsDir })
            {
                if (AssetDatabase.IsValidFolder(dir)) continue;
                string parent = Path.GetDirectoryName(dir).Replace('\\', '/');
                AssetDatabase.CreateFolder(parent, Path.GetFileName(dir));
            }
        }

        public static GameObject CreateLight()
        {
            var go = new GameObject("Directional Light");
            var light = go.AddComponent<Light>();
            light.type = LightType.Directional;
            light.intensity = 1.2f;
            light.shadows = LightShadows.Soft;
            go.transform.rotation = Quaternion.Euler(55f, -35f, 0f);

            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(0.55f, 0.55f, 0.58f);
            return go;
        }

        public static Camera CreateCamera(Vector3 pos, Vector3 euler)
        {
            var go = new GameObject("Main Camera") { tag = "MainCamera" };
            go.transform.SetPositionAndRotation(pos, Quaternion.Euler(euler));
            var cam = go.AddComponent<Camera>();
            cam.nearClipPlane = 0.02f;
            cam.farClipPlane = 100f;
            cam.fieldOfView = 70f;
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.12f, 0.13f, 0.15f);
            go.AddComponent<AudioListener>();
            go.AddComponent<RoomAR.FlyCamera>();
            return cam;
        }

        public static RoomAR.SandboxController CreateSandbox(Camera cam)
        {
            var go = new GameObject("Sandbox");
            var sb = go.AddComponent<RoomAR.SandboxController>();
            var so = new SerializedObject(sb);
            so.FindProperty("ballPhysicsMaterial").objectReferenceValue = GetBallPhysicsMaterial();
            so.FindProperty("ballMaterial").objectReferenceValue = GetLitMaterial("Ball", new Color(0.95f, 0.35f, 0.2f), 0.6f);
            so.FindProperty("cam").objectReferenceValue = cam;
            so.ApplyModifiedPropertiesWithoutUndo();
            return sb;
        }

        static void CreateBoxRoom()
        {
            var room = new GameObject("BoxRoom").transform;
            var floorMat = GetLitMaterial("Floor", new Color(0.62f, 0.55f, 0.47f), 0.2f);
            var wallMat = GetLitMaterial("Wall", new Color(0.88f, 0.88f, 0.85f), 0.1f);
            var furnMat = GetLitMaterial("Furniture", new Color(0.35f, 0.42f, 0.55f), 0.3f);

            float hx = RoomX / 2f, hz = RoomZ / 2f;
            // 안쪽 면이 정확히 실측 크기가 되도록 두께만큼 바깥으로 배치
            Box(room, "Floor",   new Vector3(0, -WallT / 2, 0),          new Vector3(RoomX + 2 * WallT, WallT, RoomZ + 2 * WallT), floorMat);
            Box(room, "Ceiling", new Vector3(0, RoomH + WallT / 2, 0),   new Vector3(RoomX + 2 * WallT, WallT, RoomZ + 2 * WallT), wallMat, castShadows: false);
            Box(room, "Wall_+X", new Vector3(hx + WallT / 2, RoomH / 2, 0), new Vector3(WallT, RoomH, RoomZ), wallMat);
            Box(room, "Wall_-X", new Vector3(-hx - WallT / 2, RoomH / 2, 0), new Vector3(WallT, RoomH, RoomZ), wallMat);
            Box(room, "Wall_+Z", new Vector3(0, RoomH / 2, hz + WallT / 2), new Vector3(RoomX + 2 * WallT, RoomH, WallT), wallMat);
            Box(room, "Wall_-Z", new Vector3(0, RoomH / 2, -hz - WallT / 2), new Vector3(RoomX + 2 * WallT, RoomH, WallT), wallMat);

            // 가구 대용 (공이 부딪힐 대상). 실제 배치와는 무관한 자리표시자입니다.
            var furn = new GameObject("Furniture (placeholder)").transform;
            furn.SetParent(room, false);
            Box(furn, "Desk",  new Vector3(hx - 0.35f, 0.375f, 0.4f),  new Vector3(0.7f, 0.75f, 1.2f), furnMat);
            Box(furn, "Bed",   new Vector3(-hx + 0.5f, 0.225f, 0.2f),  new Vector3(1.0f, 0.45f, 2.0f), furnMat);
            Box(furn, "Shelf", new Vector3(0.3f, 0.9f, hz - 0.15f),    new Vector3(0.8f, 1.8f, 0.3f), furnMat);
        }

        static GameObject Box(Transform parent, string name, Vector3 center, Vector3 size, Material mat, bool castShadows = true)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
            go.name = name;
            go.transform.SetParent(parent, false);
            go.transform.localPosition = center;
            go.transform.localScale = size;
            go.isStatic = true;
            var mr = go.GetComponent<MeshRenderer>();
            mr.sharedMaterial = mat;
            mr.shadowCastingMode = castShadows ? ShadowCastingMode.On : ShadowCastingMode.Off;
            return go;
        }

        // ---------- 에셋 ----------

        public static PhysicsMaterial GetBallPhysicsMaterial()
        {
            string path = PhysicsDir + "/BallPhysics.asset";
            var pm = AssetDatabase.LoadAssetAtPath<PhysicsMaterial>(path);
            if (pm != null) return pm; // 사용자가 조절한 값 보존
            pm = new PhysicsMaterial("Ball")
            {
                bounciness = 0.8f,
                dynamicFriction = 0.3f,
                staticFriction = 0.3f,
                bounceCombine = PhysicsMaterialCombine.Maximum,
                frictionCombine = PhysicsMaterialCombine.Average,
            };
            AssetDatabase.CreateAsset(pm, path);
            return pm;
        }

        public static Material GetLitMaterial(string name, Color color, float smoothness)
        {
            string path = $"{MaterialsDir}/{name}.mat";
            var mat = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (mat == null)
            {
                var shader = Shader.Find("Universal Render Pipeline/Lit");
                mat = new Material(shader) { name = name };
                AssetDatabase.CreateAsset(mat, path);
            }
            mat.SetColor("_BaseColor", color);
            mat.SetFloat("_Smoothness", smoothness);
            EditorUtility.SetDirty(mat);
            return mat;
        }

        public static void RegisterBuildScenes(params string[] extra)
        {
            var paths = new List<string> { BoxRoomScenePath };
            paths.AddRange(extra);
            foreach (var s in EditorBuildSettings.scenes)
                if (!paths.Contains(s.path) && File.Exists(s.path)) paths.Add(s.path);
            EditorBuildSettings.scenes = paths.Where(File.Exists)
                .Select(p => new EditorBuildSettingsScene(p, true)).ToArray();
            AssetDatabase.SaveAssets();
        }
    }
}
