# Java

Markers: `pom.xml` (Maven), `build.gradle`, `build.gradle.kts`, `settings.gradle*` (Gradle). Toolchain pin: Maven wrapper (`mvnw`, `.mvn/wrapper/`), Gradle wrapper (`gradlew`, `gradle/wrapper/gradle-wrapper.properties`), `maven.compiler.release`/`<release>`, Gradle `java { toolchain { languageVersion = ... } }`, `.sdkmanrc`, `.java-version`. Lockfiles are rare: Gradle dependency locking (`gradle.lockfile`) or Maven with fixed versions and the Enforcer plugin. Do not score a missing lockfile as 0 for Maven; say "Maven resolves fixed versions; ranges are the risk" and grep for version ranges (`[1.0,` or `+` in Gradle).

Multi-module: Maven `<modules>`, Gradle `include(...)` in `settings.gradle*`; treat the root build as one subproject and list the modules.

## Environment

Java tools run through the build: the plugin must be in the build file. Every command builds the project (runs annotation processors and build logic: project code) and downloads dependencies into `~/.m2` or `~/.gradle` (outside the repo). The build writes `target/` or `build/` into the repo (normally git-ignored). Use the wrapper (`./mvnw`, `./gradlew`) when it exists. A first build can take many minutes; say so in step 4.

A tool that is not in the build cannot run ephemerally in a useful way: report it as absent and recommend the plugin.

## Tools

| tool | category | config | tier 1 command | notes |
|---|---|---|---|---|
| `checkstyle` | lint | `checkstyle.xml`, `config/checkstyle/*.xml`, the plugin in the build | Maven: `./mvnw -B -q checkstyle:check`; Gradle: `./gradlew checkstyleMain` | Maven's default rules without a config file are `sun_checks` and very noisy: run only when the build configures it. |
| `pmd` | lint | the plugin in the build | Maven: `./mvnw -B -q pmd:check`; Gradle: `./gradlew pmdMain` | |
| `spotless` | format | the plugin in the build | Maven: `./mvnw -B -q spotless:check`; Gradle: `./gradlew spotlessCheck` | Usually wraps google-java-format or palantir-java-format. |
| `google-java-format` | format | in the build or CI | through spotless or the CI step that runs it | |
| `javac-strict` | types | `-Werror`, `-Xlint` in compiler args | the build's compile step: `./mvnw -B -q compile` / `./gradlew compileJava` and count `warning:` lines | |
| `spotbugs` | static | `spotbugs-exclude.xml`, the plugin in the build | Maven: `./mvnw -B -q compile spotbugs:check`; Gradle: `./gradlew spotbugsMain` | |
| `error-prone` | static | `errorprone` in the build | runs inside the compile step | Reports as compiler warnings and errors. |
| `junit` | tests | JUnit in build dependencies | Maven: `./mvnw -B test`; Gradle: `./gradlew test` | Results in `target/surefire-reports/` or `build/test-results/`: count tests, failures, skipped from the XML. |
| `testng` | tests | TestNG in build dependencies | as junit | |
| `jacoco` | coverage | the plugin in the build | Maven: `./mvnw -B test jacoco:report`; Gradle: `./gradlew test jacocoTestReport` | Total from `jacoco.csv` or the HTML index. Gate: Maven `jacoco:check` rules, Gradle `jacocoTestCoverageVerification`. |
| `dependency-check` | deps_audit | the OWASP plugin in the build | recommend only unless configured; it downloads the NVD database (slow; an NVD API key is advised) | Dependabot or Renovate plus GitHub's dependency graph is the light alternative. |
| `archunit` | arch | `archunit` in build dependencies | runs inside the tests | Counts when CI runs the suite that holds the ArchUnit tests. Freeze existing violations with `FreezingArchRule`. |
| `spring-modulith` | arch | `spring-modulith` in build dependencies | runs inside the tests (`ApplicationModules.of(App.class).verify()`) | Module boundaries for Spring Boot apps. |

## Suppressions

`@SuppressWarnings` (with the warning names), `// NOPMD`, `// CHECKSTYLE:OFF`, `@SuppressFBWarnings`. Count `catch (Exception` and `catch (Throwable` as a review signal for the `errors` dimension.

## First steps for recommendations

Gradle (Kotlin DSL):

```kotlin
plugins {
    java
    checkstyle
    jacoco
    id("com.diffplug.spotless") version "<latest>"
}
spotless { java { googleJavaFormat() } }
tasks.check { dependsOn(tasks.jacocoTestCoverageVerification) }
```

Maven: `maven-checkstyle-plugin` and `spotless-maven-plugin` bound to the `verify` phase, so `./mvnw verify` in CI runs them.

CI step: `./gradlew check` or `./mvnw -B verify`. Both run tests and every configured check in one command.

Error Prone catches real bugs at compile time with few false positives; add it before a large rule set like PMD.

Architecture rules, with ArchUnit (add `com.tngtech.archunit:archunit-junit5` as a test dependency; freeze today's violations so the rule passes now and blocks new ones):

```java
@AnalyzeClasses(packages = "com.example")
class ArchitectureTest {
  @ArchTest static final ArchRule layers = FreezingArchRule.freeze(
      layeredArchitecture().consideringAllDependencies()
          .layer("Web").definedBy("..web..")
          .layer("Service").definedBy("..service..")
          .layer("Persistence").definedBy("..persistence..")
          .whereLayer("Web").mayNotBeAccessedByAnyLayer()
          .whereLayer("Service").mayOnlyBeAccessedByLayers("Web"));
}
```

It runs with the tests: no new CI step.
