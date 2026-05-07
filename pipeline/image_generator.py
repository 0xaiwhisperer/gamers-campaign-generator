from __future__ import annotations

"""
image_generator.py
Wraps OpenAI gpt-image-1 APIs.

Text rendering is handled natively by the model.
Supports per-game themed prompts for gaming campaigns.
"""

import base64
import logging
import os
from pathlib import Path

from PIL import Image, ImageDraw


ASPECT_RATIO_TO_NATIVE_SIZE = {
    "1x1":  "1024x1024",
    "9x16": "1024x1536",
    "16x9": "1536x1024",
}

NATIVE_SIZE_DIMENSIONS = {
    "1024x1024": (1024, 1024),
    "1024x1536": (1024, 1536),
    "1536x1024": (1536, 1024),
}


class ImageGenerator:
    def __init__(self, logger: logging.Logger, dry_run: bool = False):
        self.logger = logger
        self.dry_run = dry_run

        if not dry_run:
            try:
                from openai import OpenAI
                api_key = os.environ.get("OPENAI_API_KEY")
                if not api_key:
                    raise EnvironmentError(
                        "OPENAI_API_KEY is not set.\n"
                        "  Copy .env.example to .env and add your key:\n"
                        "      OPENAI_API_KEY=sk-..."
                    )
                self.client = OpenAI(api_key=api_key)
            except ImportError:
                raise ImportError("openai package is required — pip install openai")

    # ── Public API ─────────────────────────────────────────────────────────────

    def build_prompt(self, product: dict, brief: dict) -> str:
        """
        Hero image — hyper-realistic product photography on a clean background.
        Establishes the exact bag appearance used as source for all edit variations.
        """
        name      = product["name"]
        spec      = product.get("product_visual_spec", {})
        art_style = brief.get("base_art_style", {})

        photo_style     = art_style.get("photography_style", "Commercial product photography, shallow depth of field.")
        product_surface = art_style.get("product_surface", "Physically accurate surface materials, crisp specular highlights.")

        if spec:
            skip_keys = {"description", "consistency_instruction"}
            detail_lines = []
            for field, val in spec.items():
                if field not in skip_keys and val:
                    label = field.replace("_", " ").title()
                    detail_lines.append(f"- {label}: {val}")

            return (
                f"Hyper-realistic commercial product photograph of '{name}'.\n"
                f"{spec.get('description', '')}\n"
                f"Photography: {photo_style} {product_surface}\n"
                f"Lighting: Professional three-point studio lighting. Strong key light from upper-left, "
                f"soft fill, crisp rim light separating the product from the background.\n"
                f"Product details:\n"
                + "\n".join(detail_lines) + "\n"
                "Background: pure clean white or very light neutral grey studio backdrop, "
                "slight soft shadow beneath the product. No scene, no clutter, no text beyond the label. "
                "Shot quality: magazine product photography, ultra-sharp, commercially perfect."
            )

        return (
            f"Hyper-realistic commercial product photograph of '{name}'. "
            "Studio lighting, shallow depth of field, clean white background. "
            "Ultra-sharp focus on the product, magazine-quality product shot."
        )

    def generate(self, prompt: str, output_path: Path) -> Path:
        """Generate a clean 1024x1024 hero image."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self.dry_run:
            return self._placeholder(output_path, 1024, 1024, label="HERO")

        self.logger.info(f"images.generate — prompt: {prompt[:80]}...")

        result = self.client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1024x1024",
            quality="medium",
            output_format="png",
            n=1,
        )
        return self._save_b64(result.data[0].b64_json, output_path)

    def create_variation(
        self,
        source_path: Path,
        ratio_label: str,
        product: dict,
        brief: dict,
        output_path: Path,
        gaming_theme: dict | None = None,
    ) -> tuple:
        """
        Use gpt-image-1 images.edit to produce a final ad creative.
        Campaign text and any gaming theme are baked into the prompt —
        the model renders typography natively.

        gaming_theme: one entry from product["gaming_themes"], e.g.
            { "game": "Fortnite", "style": "...", "message": "...", "audience": "..." }

        Returns (output_path, (width, height)).
        """
        native_size   = ASPECT_RATIO_TO_NATIVE_SIZE[ratio_label]
        width, height = NATIVE_SIZE_DIMENSIONS[native_size]
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self.dry_run:
            label = f"{gaming_theme['game']} · {ratio_label}" if gaming_theme else ratio_label
            return self._placeholder(output_path, width, height, label=label), (width, height)

        prompt = self._build_ad_prompt(ratio_label, product, brief, gaming_theme)

        game_tag = f"game={gaming_theme['game']}, " if gaming_theme else ""
        self.logger.info(
            f"images.edit — {game_tag}size={native_size}, ratio={ratio_label}, "
            f"product={product['name']}"
        )

        with open(source_path, "rb") as img_file:
            result = self.client.images.edit(
                model="gpt-image-1",
                image=img_file,
                prompt=prompt,
                size=native_size,
                quality="medium",
                n=1,
            )

        return self._save_b64(result.data[0].b64_json, output_path), (width, height)

    # ── Prompt builder ─────────────────────────────────────────────────────────

    def _build_ad_prompt(
        self,
        ratio_label: str,
        product: dict,
        brief: dict,
        gaming_theme: dict | None = None,
    ) -> str:
        name        = product.get("display_name", product["name"])
        message     = product.get("campaign_message", brief.get("campaign_message", ""))
        cta         = product.get("cta") or brief.get("cta", "")
        region      = brief.get("region", "global")
        layout_hint = self._layout_hint(ratio_label)
        text_pos    = self._text_position_hint(ratio_label)
        spec        = product.get("product_visual_spec", {})
        art_style   = brief.get("base_art_style", {})

        # ── PHOTOGRAPHY STYLE ────────────────────────────────────────────────
        style_block = (
            f"PHOTOGRAPHY STYLE:\n"
            f"{art_style.get('description', 'Commercial product photography.')}\n"
            f"- Lens & DOF: {art_style.get('photography_style', '')}\n"
            f"- Lighting: {art_style.get('lighting', '')}\n"
            f"- Product surface: {art_style.get('product_surface', '')}\n"
            f"- Depth of field: {art_style.get('depth_of_field', '')}\n"
            f"- Color grade: {art_style.get('color_grading', '')}\n"
            f"- Composition: {art_style.get('composition', '')}"
        ) if art_style else "Hyper-realistic commercial product photography, shallow depth of field, beautiful bokeh background."

        # ── PRODUCT ──────────────────────────────────────────────────────────
        if spec:
            # Output ALL spec fields so any product type is fully described.
            # description is used as the header; consistency_instruction goes last.
            header = spec.get("description", f"'{name}' product")
            product_lines = [f"PRODUCT — tack-sharp, in perfect focus, identical in every image:\n{header}"]

            # Skip these meta/structural keys — the rest all become prompt lines
            skip_keys = {"description", "consistency_instruction"}
            for field, val in spec.items():
                if field not in skip_keys and val:
                    label = field.replace("_", " ").title()
                    product_lines.append(f"- {label}: {val}")

            # Always put consistency instruction last so the model sees it as a final directive
            if spec.get("consistency_instruction"):
                product_lines.append(f"- CRITICAL — CONSISTENCY: {spec['consistency_instruction']}")

            product_block = "\n".join(product_lines)
        else:
            product_block = f"The '{name}' product — perfectly sharp, dominant in the frame."

        # ── SCENE ────────────────────────────────────────────────────────────
        if gaming_theme:
            game     = gaming_theme.get("game", "")
            message  = gaming_theme.get("message", message)
            scene    = gaming_theme.get("style", "")
            audience = gaming_theme.get("audience", "")

            scene_block = (
                f"BACKGROUND SCENE — '{game}' game world (blurred bokeh behind sharp product):\n"
                f"{scene}\n"
                f"Audience: {audience}."
            )
        else:
            scene_block = f"Clean studio background. Target market: {region}."

        # ── AD COPY ──────────────────────────────────────────────────────────
        text_lines = [f'"{message}"']
        if cta:
            text_lines.append(f'"{cta}"')

        text_block = (
            f"AD COPY — overlaid in the {text_pos}:\n"
            f"Headline: {text_lines[0]} — large, bold, clean modern sans-serif or bold rounded font. "
            f"White or bright yellow text with a subtle dark drop shadow for legibility against any background. "
            + (f"CTA button: {text_lines[1]} — pill-shaped button, high contrast." if cta else "")
        )

        return (
            f"Professional commercial product advertisement photograph. {layout_hint} format.\n\n"
            f"{style_block}\n\n"
            f"{product_block}\n\n"
            f"{scene_block}\n\n"
            f"{text_block}\n\n"
            "Final image quality: magazine-cover product photography meets cinematic game art. "
            "The product is the undeniable hero — sharp, real, premium. "
            "The game world gives atmosphere and context through beautiful bokeh."
        )

    @staticmethod
    def _layout_hint(ratio_label: str) -> str:
        return {
            "1x1":  "square (1:1) format for Instagram and Facebook feed",
            "9x16": "vertical (9:16) format for Stories and Reels",
            "16x9": "horizontal (16:9) format for YouTube banners and LinkedIn",
        }.get(ratio_label, ratio_label)

    @staticmethod
    def _text_position_hint(ratio_label: str) -> str:
        return {
            "1x1":  "lower third",
            "9x16": "lower quarter",
            "16x9": "left side or lower third",
        }.get(ratio_label, "lower portion")

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _save_b64(self, b64_data: str, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64_data))
        return path

    def _placeholder(self, path: Path, w: int, h: int, label: str = "") -> Path:
        img  = Image.new("RGBA", (w, h), (20, 20, 28, 255))
        draw = ImageDraw.Draw(img)
        lines = ["[DRY RUN]", label, f"{w}x{h}"]
        y = h // 2 - len(lines) * 14
        for line in lines:
            bbox = draw.textbbox((0, 0), line)
            tw = bbox[2] - bbox[0]
            draw.text((w // 2 - tw // 2, y), line, fill=(100, 100, 120))
            y += 28
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, format="PNG")
        return path
