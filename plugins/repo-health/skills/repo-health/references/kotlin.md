# Kotlin

Markers: `build.gradle.kts` or `build.gradle` with the Kotlin plugin, `.kt` files; Maven with `kotlin-maven-plugin`. Android: `com.android.application`/`com.android.library` plugins, `AndroidManifest.xml`. Toolchain pin and multi-module: as in `java.md` (Gradle wrapper, `jvmToolchain`, `settings.gradle.kts`). Version catalogs: `gradle/libs.versions.toml` holds plugin and library versions.

Kotlin projects also use the Java tools in `java.md` for tests (`junit`), coverage (`jacoco`), formatting (`spotless`) and dependency audit (`dependency-check`). Read both files.

## Environment

As in `java.md`: tools run through Gradle, build the project, and write `build/`. Find a plugin's task names with `./gradlew tasks --all` and grep, because names differ between plugin versions. Android builds need the Android SDK; if `ANDROID_HOME` is not set, mark Android tier 1 steps "not run: no Android SDK".

## Tools

| tool | category | config | tier 1 command | notes |
|---|---|---|---|---|
| `detekt` | lint | `detekt.yml`, `detekt-config.yml`, `config/detekt/*.yml`, the plugin in the build | `./gradlew detekt` | Baseline: `./gradlew detektBaseline` writes `baseline.xml` (recommend; it is a project file). Also covers code smells and complexity. |
| `ktlint` | lint | `.editorconfig` with `ktlint_` keys, the plugin in the build | `./gradlew ktlintCheck` (jlleitschuh plugin) or the `ktlint` CLI if installed | Style and formatting. |
| `ktfmt` | format | the plugin in the build | `./gradlew ktfmtCheck` | |
| `kotlin-strict` | types | `allWarningsAsErrors` in the build | the compile step: `./gradlew compileKotlin` and count `w:` lines | |
| `kotest` | tests | Kotest in build dependencies | `./gradlew test` | |
| `kover` | coverage | the plugin in the build | `./gradlew koverLog` or `koverXmlReport` (check the task list) | Gate: `kover { reports { verify { rule { minBound(70) } } } }`. |
| `konsist` | arch | `konsist` in build dependencies | runs inside the tests | Kotlin-aware architecture and convention checks; ArchUnit also works (inherited from Java). |

## Suppressions

`@Suppress(` with the names, `@SuppressWarnings`, detekt baseline size (number of `<ID>` entries in `baseline.xml`), ktlint `// ktlint-disable` (old) and `@Suppress("ktlint:...")`. Count `!!` (not-null assertions) as a null-safety signal and `catch (e: Exception)` / `runCatching` that ignore the failure as a signal for the `errors` dimension.

## First steps for recommendations

```kotlin
plugins {
    id("io.gitlab.arturbosch.detekt") version "<latest>"
    id("org.jlleitschuh.gradle.ktlint") version "<latest>"
    id("org.jetbrains.kotlinx.kover") version "<latest>"
}
detekt { buildUponDefaultConfig = true; baseline = file("detekt-baseline.xml") }
kotlin { compilerOptions { allWarningsAsErrors = true } }
```

CI: `./gradlew check` runs tests, detekt and ktlint once the plugins are applied. Start detekt with a baseline so CI fails only on new findings.

Architecture rules, with Konsist (`com.lemonappdev:konsist` as a test dependency):

```kotlin
class ArchitectureTest {
  @Test fun `domain does not depend on data`() {
    Konsist.scopeFromProject().assertArchitecture {
      val domain = Layer("Domain", "com.example.domain..")
      val data = Layer("Data", "com.example.data..")
      domain.dependsOnNothing(); data.dependsOn(domain)
    }
  }
}
```
