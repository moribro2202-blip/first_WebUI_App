---
name: uiux-test
description: React Native/ExpoのUI/UXテスト作成ガイド。コンポーネントテスト、スナップショットテスト、アクセシビリティテスト、インタラクションテストのベストプラクティスを提供。UIテスト、コンポーネントテスト作成時に使用。
---

# UI/UX テスト ベストプラクティス

React Native/Expo プロジェクトにおけるUI/UXテストのガイド。

## When to Use This Skill

- UIコンポーネントのテストを作成する時
- スナップショットテストを追加する時
- アクセシビリティテストを書く時
- ユーザーインタラクションのテストを書く時

## テストファイル配置

```
src/
├── components/
│   ├── ui/
│   │   ├── Button.tsx
│   │   └── __tests__/
│   │       └── Button.test.tsx
│   └── features/
│       ├── auth/
│       │   ├── LoginForm.tsx
│       │   └── __tests__/
│       │       └── LoginForm.test.tsx
```

## 基本構造

```typescript
import { render, screen, fireEvent } from "@testing-library/react-native";
import { Button } from "../Button";

describe("Button", () => {
  // レンダリングテスト
  it("renders correctly with label", () => {
    render(<Button label="送信" onPress={() => {}} />);
    expect(screen.getByText("送信")).toBeTruthy();
  });

  // インタラクションテスト
  it("calls onPress when pressed", () => {
    const onPressMock = jest.fn();
    render(<Button label="送信" onPress={onPressMock} />);

    fireEvent.press(screen.getByText("送信"));

    expect(onPressMock).toHaveBeenCalledTimes(1);
  });

  // 状態テスト
  it("is disabled when disabled prop is true", () => {
    const onPressMock = jest.fn();
    render(<Button label="送信" onPress={onPressMock} disabled />);

    fireEvent.press(screen.getByText("送信"));

    expect(onPressMock).not.toHaveBeenCalled();
  });
});
```

## アクセシビリティテスト

```typescript
describe("Button accessibility", () => {
  it("has correct accessibility label", () => {
    render(
      <Button
        label="送信"
        onPress={() => {}}
        accessibilityLabel="フォームを送信"
      />
    );

    expect(screen.getByLabelText("フォームを送信")).toBeTruthy();
  });

  it("has correct accessibility role", () => {
    render(<Button label="送信" onPress={() => {}} />);

    expect(screen.getByRole("button")).toBeTruthy();
  });

  it("announces disabled state", () => {
    render(<Button label="送信" onPress={() => {}} disabled />);

    const button = screen.getByRole("button");
    expect(button.props.accessibilityState.disabled).toBe(true);
  });
});
```

## スナップショットテスト

```typescript
import { render } from "@testing-library/react-native";
import { Card } from "../Card";

describe("Card snapshots", () => {
  it("matches snapshot with default props", () => {
    const { toJSON } = render(
      <Card title="タイトル">
        <Text>コンテンツ</Text>
      </Card>
    );

    expect(toJSON()).toMatchSnapshot();
  });

  it("matches snapshot with custom className", () => {
    const { toJSON } = render(
      <Card title="タイトル" className="bg-blue-500">
        <Text>コンテンツ</Text>
      </Card>
    );

    expect(toJSON()).toMatchSnapshot();
  });
});
```

## フォームテスト

```typescript
import { render, screen, fireEvent, waitFor } from "@testing-library/react-native";
import { LoginForm } from "../LoginForm";

describe("LoginForm", () => {
  it("shows validation error for empty email", async () => {
    render(<LoginForm onSubmit={() => {}} />);

    fireEvent.press(screen.getByText("ログイン"));

    await waitFor(() => {
      expect(screen.getByText("メールアドレスを入力してください")).toBeTruthy();
    });
  });

  it("shows validation error for invalid email", async () => {
    render(<LoginForm onSubmit={() => {}} />);

    fireEvent.changeText(
      screen.getByPlaceholderText("メールアドレス"),
      "invalid-email"
    );
    fireEvent.press(screen.getByText("ログイン"));

    await waitFor(() => {
      expect(screen.getByText("有効なメールアドレスを入力してください")).toBeTruthy();
    });
  });

  it("submits form with valid data", async () => {
    const onSubmitMock = jest.fn();
    render(<LoginForm onSubmit={onSubmitMock} />);

    fireEvent.changeText(
      screen.getByPlaceholderText("メールアドレス"),
      "test@example.com"
    );
    fireEvent.changeText(
      screen.getByPlaceholderText("パスワード"),
      "password123"
    );
    fireEvent.press(screen.getByText("ログイン"));

    await waitFor(() => {
      expect(onSubmitMock).toHaveBeenCalledWith({
        email: "test@example.com",
        password: "password123",
      });
    });
  });
});
```

## ローディング状態テスト

```typescript
describe("Button loading state", () => {
  it("shows loading indicator when loading", () => {
    render(<Button label="送信" onPress={() => {}} isLoading />);

    expect(screen.getByTestId("loading-indicator")).toBeTruthy();
    expect(screen.queryByText("送信")).toBeNull();
  });

  it("disables interaction when loading", () => {
    const onPressMock = jest.fn();
    render(<Button label="送信" onPress={onPressMock} isLoading />);

    fireEvent.press(screen.getByTestId("loading-indicator"));

    expect(onPressMock).not.toHaveBeenCalled();
  });
});
```

## リストテスト（FlashList）

```typescript
import { render, screen } from "@testing-library/react-native";
import { ItemList } from "../ItemList";

const mockItems = [
  { id: "1", title: "アイテム1" },
  { id: "2", title: "アイテム2" },
  { id: "3", title: "アイテム3" },
];

describe("ItemList", () => {
  it("renders all items", () => {
    render(<ItemList items={mockItems} />);

    expect(screen.getByText("アイテム1")).toBeTruthy();
    expect(screen.getByText("アイテム2")).toBeTruthy();
    expect(screen.getByText("アイテム3")).toBeTruthy();
  });

  it("renders empty state when no items", () => {
    render(<ItemList items={[]} />);

    expect(screen.getByText("アイテムがありません")).toBeTruthy();
  });
});
```

## モック設定

### ナビゲーションモック

```typescript
// jest.setup.js
jest.mock("expo-router", () => ({
  router: {
    push: jest.fn(),
    replace: jest.fn(),
    back: jest.fn(),
  },
  useLocalSearchParams: () => ({}),
  Link: ({ children }) => children,
}));
```

### 画像モック

```typescript
jest.mock("expo-image", () => ({
  Image: "Image",
}));
```

### Haptics モック

```typescript
jest.mock("expo-haptics", () => ({
  impactAsync: jest.fn(),
  notificationAsync: jest.fn(),
}));
```

## AI Assistant Instructions

テスト作成時は以下を遵守:

1. **必ず実際の機能を検証する** - `expect(true).toBe(true)` は禁止
2. **ユーザー視点でテストを書く** - 実装詳細ではなく振る舞いをテスト
3. **アクセシビリティを検証** - accessibilityLabel, accessibilityRole を確認
4. **境界値・異常系をテスト** - 空データ、無効な入力、エラー状態
5. **テストIDよりテキスト/ロールを優先** - `getByText`, `getByRole` を使用

### テスト命名規則

```typescript
// ✅ Good: 振る舞いを説明
it("shows error message when email is invalid", () => {});
it("navigates to profile screen when avatar is pressed", () => {});

// ❌ Bad: 実装詳細
it("sets isError to true", () => {});
it("calls handlePress function", () => {});
```

### カバレッジ目標

- UIコンポーネント: 80%以上
- フォームコンポーネント: 90%以上（バリデーション含む）
- 重要なユーザーフロー: 100%
