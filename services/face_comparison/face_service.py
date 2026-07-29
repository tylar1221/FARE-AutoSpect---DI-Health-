# services/face_comparison/face_service.py
import cv2
import torch
import numpy as np
from PIL import Image
from torchvision.transforms import Compose, ToTensor, Normalize
from transformers import AutoModel, PreTrainedModel
from huggingface_hub import snapshot_download
from insightface.app import FaceAnalysis
from insightface.utils import face_align
import os
import sys
import yaml
import re
import logging
import warnings
from typing import Dict, Tuple, Optional
import shutil

warnings.filterwarnings('ignore')

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger("face_service")

# ============================================================
# TRANSFORMERS v5 COMPATIBILITY PATCH
# ============================================================
# Older trust_remote_code=True model repos (like this AdaFace wrapper,
# written for transformers v4) never call self.post_init() correctly in
# their __init__, so `all_tied_weights_keys` never gets created on the
# instance. transformers v5's from_pretrained() unconditionally reads
# this attribute during _finalize_model_loading(), which crashes with:
#   AttributeError: 'CVLFaceRecognitionModel' object has no attribute
#   'all_tied_weights_keys'
#
# Fix: give the base PreTrainedModel class a safe default. Any subclass
# that doesn't set its own value (like this remote-code model) falls
# back to this empty dict via normal attribute lookup, and the `.keys()`
# call in transformers' internals then works instead of crashing.
if not hasattr(PreTrainedModel, 'all_tied_weights_keys') or not isinstance(
    getattr(PreTrainedModel, 'all_tied_weights_keys', None), dict
):
    try:
        PreTrainedModel.all_tied_weights_keys = {}
        log.info("✅ Applied transformers v5 compatibility patch (all_tied_weights_keys)")
    except Exception as patch_err:
        log.warning(f"Could not apply all_tied_weights_keys patch: {patch_err}")

# ============================================================
# GLOBALS (singleton pattern - loaded once)
# ============================================================

_app = None
_model = None
_transform = None
_is_loaded = False
_load_error = None

# ============================================================
# LOADING FUNCTION
# ============================================================

def load_face_models():
    """Load all face models"""
    global _app, _model, _transform, _is_loaded, _load_error

    if _is_loaded:
        return True

    try:
        print("🚀 Loading Face Detector (SCRFD via antelopev2)...")

        _app = FaceAnalysis(
            name="antelopev2",
            allowed_modules=["detection", "recognition"]
        )
        _app.prepare(ctx_id=-1, det_size=(640, 640))
        print("✅ Face detector loaded!")

        print("📥 Loading CVLFace AdaFace IR101 WebFace12M...")

        repo_id = "minchul/cvlface_adaface_ir101_webface12m"
        cache_dir = os.path.expanduser("~/.cvlface_cache/adaface_ir101").replace('\\', '/')
        os.makedirs(cache_dir, exist_ok=True)

        print("Downloading model repo (full snapshot)...")
        cache_dir = snapshot_download(repo_id, local_dir=cache_dir)
        print(f"  ✅ Repo synced to: {cache_dir}")

        # Fix wrapper.py - only the YAML path needs patching.
        # (The tied-weights issue is now handled globally above, so we
        # don't try to string-patch the class __init__ here anymore --
        # that was fragile and silently failed if the constructor
        # signature didn't exactly match "def __init__(self, config):".)
        wrapper_path = os.path.join(cache_dir, "wrapper.py").replace('\\', '/')
        if os.path.exists(wrapper_path):
            print("🔧 Fixing wrapper.py...")
            with open(wrapper_path, 'r') as f:
                content = f.read()

            yaml_path = os.path.join(cache_dir, "pretrained_model/model.yaml").replace('\\', '/')
            content = re.sub(
                r"self\.conf\s*=\s*dict\(yaml\.safe_load\(open\([^)]+\)\)\)",
                f"self.conf = dict(yaml.safe_load(open(r'{yaml_path}')))",
                content
            )

            with open(wrapper_path, 'w') as f:
                f.write(content)

            print("✅ wrapper.py fixed")
        else:
            raise FileNotFoundError("wrapper.py was not downloaded from HuggingFace.")

        # Load model
        sys.path.insert(0, cache_dir)
        original_cwd = os.getcwd()
        os.chdir(cache_dir)

        try:
            print("🧠 Loading AdaFace model...")
            _model = AutoModel.from_pretrained(
                cache_dir,
                trust_remote_code=True,
                ignore_mismatched_sizes=True
            )
            _model.eval()
            print("✅ AdaFace loaded successfully!")
        except Exception as e:
            os.chdir(original_cwd)
            import traceback
            traceback.print_exc()
            raise RuntimeError(
                f"AdaFace model failed to load. Original error: {e}"
            )
        finally:
            os.chdir(original_cwd)

        # Create transform
        _transform = Compose([
            ToTensor(),
            Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5])
        ])

        _is_loaded = True
        return True

    except Exception as e:
        _load_error = str(e)
        log.error(f"❌ Model loading failed: {e}")
        import traceback
        traceback.print_exc()
        return False

# ============================================================
# FACE QUALITY ASSESSMENT
# ============================================================

def assess_face_quality(face_image):
    """Check if face is good quality for matching"""
    issues = []
    score = 1.0

    gray = cv2.cvtColor(face_image, cv2.COLOR_RGB2GRAY)

    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    if blur_score < 100:
        issues.append("Blurry face")
        score -= 0.3
    elif blur_score < 200:
        issues.append("Slightly blurry")
        score -= 0.1

    brightness = np.mean(gray)
    if brightness < 30:
        issues.append("Too dark")
        score -= 0.3
    elif brightness > 225:
        issues.append("Too bright")
        score -= 0.2
    elif brightness < 60 or brightness > 200:
        issues.append("Poor lighting")
        score -= 0.1

    contrast = np.std(gray)
    if contrast < 30:
        issues.append("Low contrast")
        score -= 0.2

    h, w = face_image.shape[:2]
    if h < 50 or w < 50:
        issues.append("Face too small")
        score -= 0.4

    aspect_ratio = h / w
    if aspect_ratio < 0.7 or aspect_ratio > 1.4:
        issues.append("Distorted face")
        score -= 0.2

    return max(0, min(1, score)), issues

# ============================================================
# FACE DETECTION
# ============================================================

def detect_best_face(image_path):
    """Detect faces using InsightFace/SCRFD"""
    global _app

    if _app is None:
        load_face_models()

    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")

    faces = _app.get(img)
    if len(faces) == 0:
        raise Exception(f"No face detected in {image_path}")

    best = max(faces, key=lambda f: getattr(f, 'det_score', 0.0))
    return best, img

# ============================================================
# ALIGNED FACE EXTRACTION
# ============================================================

def get_aligned_face(image_path, min_quality=0.3):
    """Detect best face and align using 5-point landmarks"""
    face, img = detect_best_face(image_path)

    if not hasattr(face, 'kps') or face.kps is None:
        raise Exception(f"No landmarks detected for face in {image_path}")

    aligned_bgr = face_align.norm_crop(img, landmark=face.kps, image_size=112)
    aligned_rgb = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2RGB)

    quality_score, issues = assess_face_quality(aligned_rgb)

    if quality_score < min_quality:
        raise Exception(f"Poor quality face: Quality={quality_score:.2f}")

    bbox = face.bbox.astype(int)
    return aligned_rgb, quality_score, issues, bbox, img

# ============================================================
# ADAPTIVE THRESHOLD
# ============================================================

def get_adaptive_threshold(quality1, quality2, is_id_photo=True):
    avg_quality = (quality1 + quality2) / 2

    if is_id_photo:
        if avg_quality > 0.8:
            return 0.40
        elif avg_quality > 0.6:
            return 0.45
        else:
            return 0.55
    else:
        if avg_quality > 0.8:
            return 0.38
        elif avg_quality > 0.6:
            return 0.42
        else:
            return 0.50

# ============================================================
# EXTRACT EMBEDDING
# ============================================================

def get_embedding(image_path, is_id_photo=True):
    """Extract embedding from aligned face"""
    global _model, _transform

    if _model is None:
        load_face_models()

    aligned_face, quality, issues, bbox, img = get_aligned_face(image_path)

    print(f"  📊 Face Quality: {quality:.2f}")
    if issues:
        print(f"  ⚠️ Issues: {', '.join(issues)}")

    img_pil = Image.fromarray(aligned_face)
    tensor = _transform(img_pil).unsqueeze(0)

    with torch.no_grad():
        emb = _model(tensor)

    emb = emb.cpu().numpy()
    emb = emb / np.linalg.norm(emb)

    return emb[0], quality, issues, bbox, img

# ============================================================
# MAIN COMPARE FUNCTION
# ============================================================

class FaceComparisonService:
    """Face comparison service using AdaFace + InsightFace"""

    def compare(self, id_photo_path: str, meet_screenshot_path: str) -> Dict:
        """Compare two faces and return results"""
        try:
            # Load models if needed
            if not load_face_models():
                return {
                    'success': False,
                    'error': _load_error or 'Failed to load face models'
                }

            # Process ID photo
            print(f"🔍 Processing ID photo: {id_photo_path}")
            emb1, quality1, issues1, bbox1, img1 = get_embedding(id_photo_path, is_id_photo=True)

            # Process meet screenshot
            print(f"🔍 Processing meet screenshot: {meet_screenshot_path}")
            emb2, quality2, issues2, bbox2, img2 = get_embedding(meet_screenshot_path, is_id_photo=False)

            # Calculate similarity
            similarity = float(np.dot(emb1, emb2))
            threshold = get_adaptive_threshold(quality1, quality2, is_id_photo=True)
            match = similarity >= threshold

            return {
                'success': True,
                'similarity': similarity,
                'threshold': threshold,
                'match': match,
                'quality1': quality1,
                'quality2': quality2,
                'issues1': issues1,
                'issues2': issues2,
                'bbox1': bbox1.tolist(),
                'bbox2': bbox2.tolist()
            }

        except Exception as e:
            print(f"❌ Face comparison error: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e)
            }

# ============================================================
# SINGLETON INSTANCE
# ============================================================

_face_service = None

def get_face_service() -> FaceComparisonService:
    """Get or create the singleton face service instance"""
    global _face_service
    if _face_service is None:
        _face_service = FaceComparisonService()
    return _face_service