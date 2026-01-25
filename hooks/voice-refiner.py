#!/usr/bin/env python3
"""
音声入力を整形するClaude Code Hook
UserPromptSubmit時に実行され、音声入力特有のノイズを除去し、
Claudeに適切なコンテキストを追加します。
"""

import json
import sys
import re

def remove_fillers(text: str) -> str:
    """日本語のフィラー（言い淀み）を除去"""
    fillers = [
        r'えーと[、,]?\s*',
        r'えっと[、,]?\s*',
        r'あのー?[、,]?\s*',
        r'あの[、,]\s*',
        r'まあ[、,]?\s*',
        r'なんか[、,]?\s*',
        r'こう[、,]?\s*',
        r'その[、,]\s*',
        r'ええと[、,]?\s*',
        r'うーん[、,]?\s*',
        r'んー[、,]?\s*',
        r'ちょっと[、,]?\s*',
    ]

    result = text
    for filler in fillers:
        result = re.sub(filler, '', result, flags=re.IGNORECASE)

    # 連続する句読点やスペースを整理
    result = re.sub(r'[、,]{2,}', '、', result)
    result = re.sub(r'\s{2,}', ' ', result)
    result = result.strip()

    return result

def fix_common_voice_errors(text: str) -> str:
    """音声認識でよくある誤変換を修正"""
    corrections = {
        # プログラミング用語
        'クロード': 'Claude',
        'クロードコード': 'Claude Code',
        'エクスポ': 'Expo',
        'リアクト': 'React',
        'リアクトネイティブ': 'React Native',
        'タイプスクリプト': 'TypeScript',
        'ジャバスクリプト': 'JavaScript',
        'ノード': 'Node',
        'エーピーアイ': 'API',
        'ジェイソン': 'JSON',
        'コンポーネント': 'コンポーネント',
        'ファンクション': '関数',
        'メソッド': 'メソッド',
        'インポート': 'import',
        'エクスポート': 'export',
        'ギット': 'Git',
        'ギットハブ': 'GitHub',
        'コミット': 'commit',
        'プッシュ': 'push',
        'プル': 'pull',
        'マージ': 'merge',
        'ブランチ': 'branch',
        # ファイル拡張子
        'ティーエスエックス': '.tsx',
        'ティーエス': '.ts',
        'ジェイエスエックス': '.jsx',
        'ジェイエス': '.js',
    }

    result = text
    for wrong, correct in corrections.items():
        result = re.sub(wrong, correct, result, flags=re.IGNORECASE)

    return result

def main():
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        # JSON解析失敗時は何もせず終了
        sys.exit(0)

    prompt = input_data.get("prompt", "")

    if not prompt:
        sys.exit(0)

    # 音声入力の整形
    cleaned_prompt = remove_fillers(prompt)
    cleaned_prompt = fix_common_voice_errors(cleaned_prompt)

    # 元のプロンプトと整形後が異なる場合のみコンテキストを追加
    if cleaned_prompt != prompt:
        context = f"""[音声入力の補正]
元の入力: {prompt}
整形後: {cleaned_prompt}

上記は音声入力によるプロンプトです。話し言葉や曖昧な表現を適切に解釈してください。"""
        print(context)
    else:
        # 音声入力であることを示すコンテキストを追加
        context = "[このプロンプトは音声入力の可能性があります。話し言葉や曖昧な表現を適切に解釈してください。]"
        print(context)

    sys.exit(0)

if __name__ == "__main__":
    main()
