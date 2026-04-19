from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from dotenv import load_dotenv
import requests


STOP_WORDS: Set[str] = {"a","an","and","are","at","be","for","from","how","i","in",
	"is","it","me","my","of","on","or","please","should","the","to",
	"what","when","which","with","you","your"}


@dataclass
class MedicationRecord:
	raw_text: str
	fields: Dict[str, str]
	line_number: int

	def short_label(self) -> str:
		pet = self.fields.get("pet", "Unknown pet")
		medicine = self.fields.get("medicine", "Unknown medicine")
		time_value = self.fields.get("time", "Unknown time")
		return f"{pet} | {medicine} | {time_value}"


@dataclass
class MedicationIndex:
	source_name: str
	records: List[MedicationRecord]


def load_environment() -> None:
	"""Load .env variables so GROQ_API_KEY is available."""
	load_dotenv()


def get_groq_api_key(override_key: Optional[str] = None) -> Optional[str]:
	"""Return API key from an optional override or environment."""
	return override_key.strip() if override_key and override_key.strip() else os.getenv("GROQ_API_KEY")


def normalize_text(value: str) -> str:
	return re.sub(r"\s+", " ", value.strip().lower())


def tokenize_without_stop_words(text: str) -> List[str]:
	tokens = re.findall(r"[a-zA-Z0-9:]+", text.lower())
	return [token for token in tokens if token not in STOP_WORDS and len(token) > 1]


def parse_medication_text(text: str) -> List[MedicationRecord]:
	records: List[MedicationRecord] = []
	for line_number, line in enumerate(text.splitlines(), start=1):
		cleaned = line.strip()
		if not cleaned:
			continue
		parts = [item.strip() for item in cleaned.split("|") if item.strip() and ":" in item]
		fields = {
			normalize_text(key): value.strip()
			for key, value in (part.split(":", 1) for part in parts)
		}
		records.append(MedicationRecord(raw_text=cleaned, fields=fields, line_number=line_number))
	return records


def build_medication_index(text: str, source_name: str) -> MedicationIndex:
	records = parse_medication_text(text)
	if not records:
		raise ValueError("No medication instructions found in the TXT file.")
	return MedicationIndex(source_name=source_name, records=records)


def load_text_file(file_path: str | Path) -> str:
	return Path(file_path).read_text(encoding="utf-8")


def _score_record(record: MedicationRecord, query_tokens: Sequence[str]) -> float:
	if not query_tokens:
		return 0.0
	record_text = normalize_text(record.raw_text)
	matched = sum(1 for token in query_tokens if token in record_text)
	time_bonus = 0.2 if any(":" in token and token in record_text for token in query_tokens) else 0.0
	return float(matched) + time_bonus


def _time_to_minutes(value: str) -> Optional[int]:
	cleaned = normalize_text(value)

	match_24h = re.search(r"\b(\d{1,2}):(\d{2})\b", cleaned)
	if match_24h:
		hour = int(match_24h.group(1))
		minute = int(match_24h.group(2))
		if 0 <= hour <= 23 and 0 <= minute <= 59:
			return hour * 60 + minute

	match_ampm = re.search(r"\b(\d{1,2})\s*(am|pm)\b", cleaned)
	if match_ampm:
		hour = int(match_ampm.group(1))
		suffix = match_ampm.group(2)
		if 1 <= hour <= 12:
			if suffix == "am":
				hour = 0 if hour == 12 else hour
			else:
				hour = 12 if hour == 12 else hour + 12
			return hour * 60

	return None


def _extract_pet_filters(question: str, index: MedicationIndex) -> Set[str]:
	question_norm = normalize_text(question)
	return {
		normalize_text(record.fields.get("pet", ""))
		for record in index.records
		if normalize_text(record.fields.get("pet", ""))
		and normalize_text(record.fields.get("pet", "")) in question_norm
	}


def _check_pet_not_found_warning(question: str, index: MedicationIndex, retrieved_records: List[MedicationRecord]) -> Optional[str]:
	"""Return warning message if pet was mentioned in question but not found in records."""
	available_pets = {
		normalize_text(record.fields.get("pet", ""))
		for record in index.records
		if record.fields.get("pet", "")
	}
	question_norm = normalize_text(question)
	mentioned_pets = {pet for pet in available_pets if pet in question_norm}
	
	if mentioned_pets and not retrieved_records:
		return f"⚠️ Pet(s) mentioned ({', '.join(mentioned_pets)}) not found in medication records."
	return None


def _extract_time_filters(question: str) -> Set[int]:
	patterns = [r"\b\d{1,2}:\d{2}\b", r"\b\d{1,2}\s*(?:am|pm)\b"]
	all_matches = [
		match
		for pattern in patterns
		for match in re.findall(pattern, question.lower())
	]
	return {parsed for parsed in (_time_to_minutes(match) for match in all_matches) if parsed is not None}


def retrieve_top_records(question: str, index: MedicationIndex, top_k: int = 3) -> List[MedicationRecord]:
	query_tokens = tokenize_without_stop_words(question)
	candidate_records = list(index.records)

	pet_filters = _extract_pet_filters(question, index)
	if pet_filters:
		candidate_records = [
			record
			for record in candidate_records
			if normalize_text(record.fields.get("pet", "")) in pet_filters
		]

	time_filters = _extract_time_filters(question)
	if time_filters:
		candidate_records = [
			record
			for record in candidate_records
			if (_time_to_minutes(record.fields.get("time", "")) in time_filters)
		]

	scored = [(_score_record(record, query_tokens), record) for record in candidate_records]
	scored.sort(key=lambda pair: pair[0], reverse=True)
	return [record for score, record in scored[:top_k] if score > 0]


def _format_context(records: Sequence[MedicationRecord]) -> str:
	if not records:
		return "No relevant medication entries were found."
	return "\n".join(f"Line {record.line_number}: {record.raw_text}" for record in records)


def _local_fallback_answer(records: Sequence[MedicationRecord], question: str) -> str:
	if not records:
		return "I could not find matching medication instructions in the uploaded TXT file."
	lines = [f"Question asked: {question}"]
	lines.extend(
		f"{record.fields.get('pet', 'Unknown pet')}: give {record.fields.get('medicine', 'Unknown medicine')} "
		f"({record.fields.get('dose', 'Unknown dose')}) at {record.fields.get('time', 'Unknown time')}."
		for record in records
	)
	return "\n".join(lines)


def _ask_groq(question: str, context: str, api_key: str) -> str:
	prompt = (
		"You are a helpful pet medication assistant. Based on the medication records below, provide a clear, natural explanation to answer the user's question.\n\n"
		"Important instructions:\n"
		"- Write in a conversational, friendly tone (not just a list)\n"
		"- Include the pet name, medicine name, dosage, time, and frequency\n"
		"- If there are notes about the medication (like why it's needed), explain those too\n"
		"- Use complete sentences and be specific\n"
		"- Do not invent information - only use what's in the context\n"
		"- Be concise, don't repeat information unnecessarily\n"
		f"Medication records:\n{context}\n\n"
		f"User question: {question}\n\n"
		"Provide a natural, helpful answer:"
	)

	headers = {
		"Authorization": f"Bearer {api_key}",
		"Content-Type": "application/json",
	}
	payload = {
		"model": "llama-3.1-8b-instant",
		"messages": [
			{"role": "system", "content": "You are a pet medication assistant."},
			{"role": "user", "content": prompt},
		],
		"temperature": 0.2,
	}

	response = requests.post(
		"https://api.groq.com/openai/v1/chat/completions",
		headers=headers,
		json=payload,
		timeout=30,
	)

	if response.status_code >= 400:
		try:
			error_message = response.json().get("error", {}).get("message", response.text)
		except ValueError:
			error_message = response.text
		raise RuntimeError(f"Groq API error ({response.status_code}): {error_message}")

	data = response.json()
	choices = data.get("choices", [])
	if not choices:
		raise RuntimeError("Groq returned no choices.")

	message = choices[0].get("message", {})
	text = message.get("content")
	if text and text.strip():
		return text.strip()
	raise RuntimeError("Groq returned an empty response.")


def answer_medication_question(
	question: str,
	index: MedicationIndex,
	top_k: int = 3,
	api_key_override: Optional[str] = None,
	include_local_fallback: bool = False,
) -> Dict[str, object]:
	if not question.strip():
		raise ValueError("Question cannot be empty.")

	records = retrieve_top_records(question, index=index, top_k=top_k)
	context = _format_context(records)
	api_key = get_groq_api_key(api_key_override)
	key_source = "user" if api_key_override and api_key_override.strip() else ("environment" if api_key else "none")
	key_fingerprint = f"...{api_key[-4:]}" if api_key and len(api_key) >= 4 else None

	local_answer = _local_fallback_answer(records, question)
	llm_answer: Optional[str] = None
	llm_error: Optional[str] = None

	if not api_key:
		answer = local_answer
	else:
		try:
			llm_answer = _ask_groq(question, context, api_key)
			answer = llm_answer
		except Exception as exc:
			llm_error = str(exc)
			answer = local_answer

	result = {
		"answer": answer,
		"records": records,
		"context": context,
		"source_name": index.source_name,
		"answer_source": "groq" if llm_answer else "local",
		"key_source": key_source,
	}

	if key_fingerprint:
		result["key_fingerprint"] = key_fingerprint

	if llm_answer is not None:
		result["groq_answer"] = llm_answer
	if llm_error:
		result["groq_error"] = llm_error

	if include_local_fallback:
		result["local_answer"] = local_answer

	return result

