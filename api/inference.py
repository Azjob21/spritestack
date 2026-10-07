import torch
import json
from transformers import pipeline, AutoTokenizer, AutoModelForTokenClassification
from spellchecker import SpellChecker

class SpriteStackParser:
    def __init__(self, model_path):
        """
        Initializes the full SpriteStack AI Pipeline:
        1. General Spell Checker (Standard English)
        2. DistilBERT NER Model (Expert Predictor)
        """
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        print(f"Using device: {self.device}")

        # 1. Initialize General Spell Checker
        self.spell = SpellChecker()

        # 2. Load the Expert Model from your local models folder
        print(f"Loading SpriteStack Model from: {model_path}...")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_path)
            # DistilBERT does not accept token_type_ids. Some saved tokenizer
            # configs still advertise them, so force the pipeline to emit only
            # the inputs supported by DistilBertForTokenClassification.
            self.tokenizer.model_input_names = ["input_ids", "attention_mask"]
            self.model = AutoModelForTokenClassification.from_pretrained(model_path)
            self.ner_pipeline = pipeline(
                "token-classification", 
                model=self.model, 
                tokenizer=self.tokenizer,
                device=self.device,
                aggregation_strategy="none" # We use our own hyphen-logic instead
            )
            print("Model loaded successfully.")
        except Exception as e:
            print(f"Error loading model: {e}")

    def _sanitize(self, text):
        """
        PRE-PROCESSING: Standard English spell correction.
        Example: 'drgon' -> 'dragon'
        """
        words = text.lower().split()
        corrected_words = []
        for word in words:
            correction = self.spell.correction(word)
            corrected_words.append(correction if correction is not None else word)
        return " ".join(corrected_words)

    def _glue_with_hyphens(self, raw_results):
        """
        POST-PROCESSING: Merges consecutive B-tags of the same type.
        Logic: 'fire' (B-OBJ) + 'dragon' (B-OBJ) = 'fire-dragon'
        """
        if not raw_results:
            return []

        merged = []
        # Start with the first entity found by the model
        current_type = raw_results[0]['entity'].split('-')[-1]
        current_word = raw_results[0]['word'].replace("##", "")

        for i in range(1, len(raw_results)):
            next_type = raw_results[i]['entity'].split('-')[-1]
            next_word = raw_results[i]['word'].replace("##", "")

            # If the tag type is the same as the previous one, glue them
            if next_type == current_type:
                current_word += f"-{next_word}"
            else:
                # Type changed: save what we have and start a new group
                merged.append({"type": current_type, "text": current_word})
                current_word = next_word
                current_type = next_type

        # Add the final entity to the list
        merged.append({"type": current_type, "text": current_word})
        return merged

    def _text_to_int(self, text):
        num_map = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "eleven": 11,
            "twelve": 12,
            "thirteen": 13,
            "fourteen": 14,
            "fifteen": 15,
            "sixteen": 16,
            "seventeen": 17,
            "eighteen": 18,
            "nineteen": 19,
            "twenty": 20,
        }
        text = text.lower()
        if text.isdigit():
            return int(text)
        return num_map.get(text, 1)  # Default to 1 if unknown

    def parse_command(self, text):
        """
        The Main Pipeline: Sanitize -> Predict -> Glue -> List-based JSON
        """

        # 1. Clean the input
        clean_text = self._sanitize(text)

        # 2. Get AI predictions
        raw_tags = self.ner_pipeline(clean_text)

        # 3. Apply the Hyphen-Glue logic
        final_entities = self._glue_with_hyphens(raw_tags)

        # 4. Format the Final JSON Structure
        output = {
            "scene_metadata": {"global_theme": "default", "raw_text": text},
            "entities": [],
        }

        # --- STEP 2: ATTRIBUTE GROUPING LOGIC ---
        # This tracks the most recent object so we can attach positions to it
        current_item = None

        # --- STEP 7: AI-DRIVEN COUNT LOGIC ---
        current_item = None
        current_count = 1  # Reset count for each new object
        global_theme = "default"

        for ent in final_entities:
            entity_type = ent["type"]
            entity_text = ent["text"]

            if entity_type == "SCENE_TYPE":
                global_theme = entity_text
                output["scene_metadata"]["global_theme"] = global_theme
                for item in output["entities"]:
                    if item["scene_type"] == "default":
                        item["scene_type"] = global_theme

            elif entity_type == "COUNT":
                # Convert the AI-found text (e.g., "three" or "5") to an integer
                current_count = self._text_to_int(entity_text)

            elif entity_type == "OBJECT":
                # Remove plural 's' at the end to match Unity Prefab names
                normalized_name = entity_text.lower()
                if normalized_name.endswith("s") and not normalized_name.endswith("ss"):
                    normalized_name = normalized_name[:-1]

                # Remove trailing hyphens if the model left any
                normalized_name = normalized_name.strip("-")

                current_item = {
                    "object": normalized_name,
                    "count": current_count,
                    "position": "center",
                    "scene_type": global_theme,
                }
                output["entities"].append(current_item)
                current_count = 1

            elif entity_type == "POSITION" and current_item is not None:
                current_item["position"] = entity_text

        # DEBUG for verification
        print(f"DEBUG: Found {len(final_entities)} distinct entity parts.")
        print(f"DEBUG: Grouped into {len(output['entities'])} individual game objects.")

        return output
