import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;

public class CandidateRunner {
    private static Class<?> typeOf(String name) throws Exception {
        if (name.endsWith("[]")) {
            return Array.newInstance(typeOf(name.substring(0, name.length() - 2)), 0).getClass();
        }
        switch (name) {
            case "byte": return byte.class;
            case "short": return short.class;
            case "int": return int.class;
            case "long": return long.class;
            case "float": return float.class;
            case "double": return double.class;
            case "boolean": return boolean.class;
            case "char": return char.class;
            case "java.lang.String": return String.class;
            default: return Class.forName(name);
        }
    }

    private static Object parse(String type, String b64) throws Exception {
        String value = new String(Base64.getDecoder().decode(b64), StandardCharsets.UTF_8);
        switch (type) {
            case "byte": return Byte.valueOf(value);
            case "short": return Short.valueOf(value);
            case "int": return Integer.valueOf(value);
            case "long": return Long.valueOf(value);
            case "float": return Float.valueOf(value);
            case "double": return Double.valueOf(value);
            case "boolean": return Boolean.valueOf(value);
            case "char": return value.isEmpty() ? Character.valueOf('\0') : Character.valueOf(value.charAt(0));
            case "java.lang.String": return value;
            case "java.lang.Comparable": return value;
            default:
                if ("__NULL__".equals(value)) return null;
                throw new IllegalArgumentException("Unsupported argument type: " + type);
        }
    }

    private static final class PlanNode {
        String strategy;
        String type;
        String className;
        String member;
        String[] parameterTypes;
        int[] children;
        String payload;
    }

    private static String decodeText(String b64) {
        return new String(Base64.getDecoder().decode(b64), StandardCharsets.UTF_8);
    }

    private static List<PlanNode> decodePlan(String encoded) {
        String raw = decodeText(encoded);
        String[] lines = raw.split("\\n", -1);
        List<PlanNode> nodes = new ArrayList<>();
        for (String line : lines) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\t", -1);
            if (fields.length != 7) {
                throw new IllegalArgumentException("Malformed construction plan row");
            }
            PlanNode node = new PlanNode();
            node.strategy = fields[0];
            node.type = fields[1];
            node.className = fields[2];
            node.member = fields[3];
            node.parameterTypes = fields[4].isEmpty() ? new String[0] : fields[4].split(",", -1);
            String[] childFields = fields[5].isEmpty() ? new String[0] : fields[5].split(",", -1);
            node.children = new int[childFields.length];
            for (int i = 0; i < childFields.length; i++) {
                node.children[i] = Integer.parseInt(childFields[i]);
                if (node.children[i] < 0 || node.children[i] >= nodes.size()) {
                    throw new IllegalArgumentException("Construction plan child must precede its parent");
                }
            }
            node.payload = fields[6];
            nodes.add(node);
        }
        if (nodes.isEmpty()) throw new IllegalArgumentException("Empty construction plan");
        return nodes;
    }

    private static Object literalValue(String valueType, String json) {
        String value = json;
        if (json.startsWith("\"") && json.endsWith("\"") && json.length() >= 2) {
            value = json.substring(1, json.length() - 1)
                .replace("\\\"", "\"")
                .replace("\\\\", "\\")
                .replace("\\n", "\n")
                .replace("\\r", "\r")
                .replace("\\t", "\t");
        }
        switch (valueType) {
            case "byte": case "java.lang.Byte": return Byte.valueOf(value);
            case "short": case "java.lang.Short": return Short.valueOf(value);
            case "int": case "java.lang.Integer": return Integer.valueOf(value);
            case "long": case "java.lang.Long": return Long.valueOf(value);
            case "float": case "java.lang.Float": return Float.valueOf(value);
            case "double": case "java.lang.Double": return Double.valueOf(value);
            case "boolean": case "java.lang.Boolean": return Boolean.valueOf(value);
            case "char": case "java.lang.Character": return value.isEmpty() ? Character.valueOf('\0') : Character.valueOf(value.charAt(0));
            case "java.lang.String": return value;
            default: throw new IllegalArgumentException("Unsupported literal value type: " + valueType);
        }
    }

    private static Object constructPlan(String encoded) throws Exception {
        List<PlanNode> nodes = decodePlan(encoded);
        Object[] values = new Object[nodes.size()];
        for (int index = 0; index < nodes.size(); index++) {
            PlanNode node = nodes.get(index);
            Object[] arguments = new Object[node.children.length];
            for (int i = 0; i < node.children.length; i++) arguments[i] = values[node.children[i]];
            Class<?>[] parameterTypes = new Class<?>[node.parameterTypes.length];
            for (int i = 0; i < parameterTypes.length; i++) parameterTypes[i] = typeOf(node.parameterTypes[i]);

            switch (node.strategy) {
                case "literal":
                    values[index] = literalValue(node.member, node.payload);
                    break;
                case "empty_array": {
                    String component = node.type.substring(0, node.type.length() - 2);
                    values[index] = Array.newInstance(typeOf(component), 0);
                    break;
                }
                case "enum_first": {
                    Object[] constants = typeOf(node.type).getEnumConstants();
                    if (constants == null || constants.length == 0) throw new IllegalArgumentException("Enum has no constants: " + node.type);
                    values[index] = constants[0];
                    break;
                }
                case "constructor":
                    values[index] = typeOf(node.className).getConstructor(parameterTypes).newInstance(arguments);
                    break;
                case "static_factory":
                    values[index] = typeOf(node.className).getMethod(node.member, parameterTypes).invoke(null, arguments);
                    break;
                case "static_field":
                    values[index] = typeOf(node.className).getField(node.member).get(null);
                    break;
                default:
                    throw new IllegalArgumentException("Unsupported construction strategy: " + node.strategy);
            }
        }
        return values[values.length - 1];
    }

    private static String enc(String value) {
        return Base64.getEncoder().encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }

    private static void emitError(Throwable t) {
        System.out.println("STATUS=ERROR");
        System.out.println("ERROR_CLASS=" + t.getClass().getName());
        System.out.println("ERROR_MESSAGE_B64=" + enc(String.valueOf(t.getMessage())));
    }
    private static boolean isSupportedArray(Object result) {
    if (result == null || !result.getClass().isArray()) {
        return false;
    }

    Class<?> componentType =
        result.getClass().getComponentType();

    return componentType.isPrimitive();
}

    private static void emitArray(Object result) {
        int length = Array.getLength(result);
        Class<?> componentType =
            result.getClass().getComponentType();

        System.out.println("RETURN_KIND=ARRAY");
        System.out.println(
            "ARRAY_COMPONENT_TYPE=" + componentType.getName()
        );
        System.out.println("ARRAY_LENGTH=" + length);
        System.out.println("RETURN_B64=");

        for (int i = 0; i < length; i++) {
            Object value = Array.get(result, i);

            System.out.println(
                "ARRAY_ITEM_"
                + i
                + "_B64="
                + enc(String.valueOf(value))
            );
        }
    }

    private static boolean isSupportedScalarType(Class<?> type) {
        return (
            type == boolean.class
            || type == byte.class
            || type == short.class
            || type == int.class
            || type == long.class
            || type == float.class
            || type == double.class
            || type == char.class
            || type == Boolean.class
            || Number.class.isAssignableFrom(type)
            || type == Character.class
            || type == String.class
        );
    }

    private static boolean emitVoidState(
        Class<?> receiverClass,
        Object receiver,
        String targetMethodName
    ) {
        if (
            !targetMethodName.startsWith("set")
            || targetMethodName.length() <= 3
        ) {
            return false;
        }

        String suffix = targetMethodName.substring(3);
        String[] observerNames = {
            "get" + suffix,
            "is" + suffix,
        };

        for (String observerName : observerNames) {
            try {
                Method observer = receiverClass.getMethod(
                    observerName
                );

                if (
                    Modifier.isStatic(observer.getModifiers())
                    || observer.getParameterCount() != 0
                    || !isSupportedScalarType(
                        observer.getReturnType()
                    )
                ) {
                    continue;
                }

                Object first = observer.invoke(receiver);
                Object second = observer.invoke(receiver);

                if (!java.util.Objects.equals(first, second)) {
                    continue;
                }

                System.out.println("RETURN_KIND=VOID_STATE");
                System.out.println("RETURN_B64=");
                System.out.println(
                    "STATE_METHOD=" + observerName
                );
                System.out.println(
                    "STATE_RETURN_TYPE="
                    + observer.getReturnType().getName()
                );

                if (first == null) {
                    System.out.println("STATE_KIND=NULL");
                    System.out.println("STATE_VALUE_B64=");
                } else {
                    System.out.println("STATE_KIND=SCALAR");
                    System.out.println(
                        "STATE_VALUE_B64="
                        + enc(String.valueOf(first))
                    );
                }

                return true;
            } catch (ReflectiveOperationException exception) {
                // This naming candidate is not a usable stable observer.
            }
        }

        return false;
    }

    private static void applySetupStep(Class<?> receiverClass, Object receiver, String stepB64) throws Exception {
        String raw = new String(Base64.getDecoder().decode(stepB64), StandardCharsets.UTF_8);
        String[] fields = raw.split("\\t", -1);
        if (fields.length < 2) throw new IllegalArgumentException("Malformed setup step");

        String methodName = fields[0];
        String[] typeNames = fields[1].isEmpty() ? new String[0] : fields[1].split(",", -1);
        if (fields.length != 2 + typeNames.length) throw new IllegalArgumentException("Setup argument count mismatch");

        Class<?>[] parameterTypes = new Class<?>[typeNames.length];
        Object[] values = new Object[typeNames.length];
        for (int i = 0; i < typeNames.length; i++) {
            String spec = fields[2 + i];
            parameterTypes[i] = typeOf(typeNames[i]);
            if (spec.startsWith("N:")) {
                String helperClassName = spec.substring(2);
                Class<?> helperClass = Class.forName(helperClassName);
                values[i] = helperClass.getConstructor().newInstance();
            } else if (spec.startsWith("V:")) {
                values[i] = parse(typeNames[i], spec.substring(2));
            } else if (spec.startsWith("P:")) {
                values[i] = constructPlan(spec.substring(2));
            } else {
                throw new IllegalArgumentException("Unknown setup argument spec: " + spec);
            }
        }

        Method setup = receiverClass.getMethod(methodName, parameterTypes);
        try {
            setup.invoke(receiver, values);
        } catch (InvocationTargetException e) {
            Throwable cause = e.getCause() == null ? e : e.getCause();
            throw new IllegalStateException("Setup step " + methodName + " failed: " + cause, cause);
        }
    }

    public static void main(String[] args) {
    try {
        if (args.length > 0 && "--plan".equals(args[0])) {
            runWithPlan(args);
            return;
        }
        if (args.length < 6) {
            throw new IllegalArgumentException(
                "Usage: <class> <ctorTypesCsv> <ctorCount> "
                + "<method> <methodTypesCsv> <setupCount> "
                + "[ctorValuesB64...] [setupStepB64...] "
                + "[methodValuesB64...]"
            );
        }

        String className = args[0];

        String constructorTypesCsv = args[1];
        String[] constructorTypeNames =
            constructorTypesCsv.isEmpty()
                ? new String[0]
                : constructorTypesCsv.split(",", -1);

        int constructorCount = Integer.parseInt(args[2]);

        if (
            constructorCount < 0
            || constructorCount != constructorTypeNames.length
        ) {
            throw new IllegalArgumentException(
                "Constructor argument count mismatch"
            );
        }

        String methodName = args[3];

        String methodTypesCsv = args[4];
        String[] methodTypeNames =
            methodTypesCsv.isEmpty()
                ? new String[0]
                : methodTypesCsv.split(",", -1);

        int setupCount = Integer.parseInt(args[5]);

        if (setupCount < 0) {
            throw new IllegalArgumentException(
                "setupCount must be >= 0"
            );
        }

        int expectedArgs =
            6
            + constructorCount
            + setupCount
            + methodTypeNames.length;

        if (args.length != expectedArgs) {
            throw new IllegalArgumentException(
                "Argument count mismatch: expected "
                + expectedArgs
                + " but got "
                + args.length
            );
        }

        Class<?> clazz = Class.forName(className);

        Class<?>[] constructorParameterTypes =
            new Class<?>[constructorCount];

        Object[] constructorValues =
            new Object[constructorCount];

        int constructorValueOffset = 6;

        for (int i = 0; i < constructorCount; i++) {
            constructorParameterTypes[i] =
                typeOf(constructorTypeNames[i]);

            constructorValues[i] = parse(
                constructorTypeNames[i],
                args[constructorValueOffset + i]
            );
        }

        Constructor<?> constructor =
            clazz.getConstructor(constructorParameterTypes);

        Object receiver =
            constructor.newInstance(constructorValues);

        int setupOffset =
            constructorValueOffset + constructorCount;

        for (int i = 0; i < setupCount; i++) {
            applySetupStep(
                clazz,
                receiver,
                args[setupOffset + i]
            );
        }

        Class<?>[] methodParameterTypes =
            new Class<?>[methodTypeNames.length];

        Object[] methodValues =
            new Object[methodTypeNames.length];

        int methodValueOffset =
            setupOffset + setupCount;

        for (int i = 0; i < methodTypeNames.length; i++) {
            methodParameterTypes[i] =
                typeOf(methodTypeNames[i]);

            methodValues[i] = parse(
                methodTypeNames[i],
                args[methodValueOffset + i]
            );
        }

        Method method = clazz.getMethod(
            methodName,
            methodParameterTypes
        );

        Object result;

        try {
            result = method.invoke(receiver, methodValues);
        } catch (InvocationTargetException exception) {
            Throwable cause =
                exception.getCause() == null
                    ? exception
                    : exception.getCause();

            System.out.println("STATUS=EXCEPTION");
            System.out.println(
                "EXCEPTION_CLASS="
                + cause.getClass().getName()
            );
            System.out.println(
                "EXCEPTION_MESSAGE_B64="
                + enc(String.valueOf(cause.getMessage()))
            );
            return;
        }

        System.out.println("STATUS=OK");
        System.out.println(
            "RETURN_TYPE=" + method.getReturnType().getName()
        );

       if (method.getReturnType() == void.class) {
    if (!emitVoidState(clazz, receiver, methodName)) {
        System.out.println("RETURN_KIND=VOID");
        System.out.println("RETURN_B64=");
    }
} else if (result == null) {
    System.out.println("RETURN_KIND=NULL");
    System.out.println("RETURN_B64=");
} else if (result == receiver) {
    System.out.println("RETURN_KIND=SAME_RECEIVER");
    System.out.println("RETURN_B64=");
} else if (isSupportedArray(result)) {
    emitArray(result);
} else if (
    result instanceof String
    || result instanceof Character
    || result instanceof Number
    || result instanceof Boolean
) {
    System.out.println("RETURN_KIND=SCALAR");
    System.out.println(
        "RETURN_B64="
        + enc(String.valueOf(result))
    );
} else {
    System.out.println("RETURN_KIND=OBJECT");
    System.out.println(
        "RETURN_B64="
        + enc(String.valueOf(result))
    );
}
    } catch (Throwable throwable) {
        emitError(throwable);
        System.exit(2);
    }
}

    private static void runWithPlan(String[] args) throws Exception {
        if (args.length < 6) {
            throw new IllegalArgumentException(
                "Usage: --plan <planB64> <class> <method> <methodTypesCsv> <setupCount> [setupStepB64...] [methodValuesB64...]"
            );
        }
        String plan = args[1];
        String className = args[2];
        String methodName = args[3];
        String[] methodTypeNames = args[4].isEmpty() ? new String[0] : args[4].split(",", -1);
        int setupCount = Integer.parseInt(args[5]);
        int expectedArgs = 6 + setupCount + methodTypeNames.length;
        if (setupCount < 0 || args.length != expectedArgs) {
            throw new IllegalArgumentException("Plan-mode argument count mismatch");
        }

        Class<?> clazz = Class.forName(className);
        Object receiver = constructPlan(plan);
        for (int i = 0; i < setupCount; i++) {
            applySetupStep(clazz, receiver, args[6 + i]);
        }
        Class<?>[] methodParameterTypes = new Class<?>[methodTypeNames.length];
        Object[] methodValues = new Object[methodTypeNames.length];
        int valueOffset = 6 + setupCount;
        for (int i = 0; i < methodTypeNames.length; i++) {
            methodParameterTypes[i] = typeOf(methodTypeNames[i]);
            methodValues[i] = parse(methodTypeNames[i], args[valueOffset + i]);
        }
        Method method = clazz.getMethod(methodName, methodParameterTypes);
        emitInvocation(clazz, receiver, method, methodValues, methodName);
    }

    private static void emitInvocation(
        Class<?> clazz, Object receiver, Method method, Object[] methodValues, String methodName
    ) throws Exception {
        Object result;
        try {
            result = method.invoke(receiver, methodValues);
        } catch (InvocationTargetException exception) {
            Throwable cause = exception.getCause() == null ? exception : exception.getCause();
            System.out.println("STATUS=EXCEPTION");
            System.out.println("EXCEPTION_CLASS=" + cause.getClass().getName());
            System.out.println("EXCEPTION_MESSAGE_B64=" + enc(String.valueOf(cause.getMessage())));
            return;
        }
        System.out.println("STATUS=OK");
        System.out.println("RETURN_TYPE=" + method.getReturnType().getName());
        if (method.getReturnType() == void.class) {
            if (!emitVoidState(clazz, receiver, methodName)) {
                System.out.println("RETURN_KIND=VOID");
                System.out.println("RETURN_B64=");
            }
        } else if (result == null) {
            System.out.println("RETURN_KIND=NULL");
            System.out.println("RETURN_B64=");
        } else if (result == receiver) {
            System.out.println("RETURN_KIND=SAME_RECEIVER");
            System.out.println("RETURN_B64=");
        } else if (isSupportedArray(result)) {
            emitArray(result);
        } else if (result instanceof String || result instanceof Character || result instanceof Number || result instanceof Boolean) {
            System.out.println("RETURN_KIND=SCALAR");
            System.out.println("RETURN_B64=" + enc(String.valueOf(result)));
        } else {
            System.out.println("RETURN_KIND=OBJECT");
            System.out.println("RETURN_B64=");
        }
    }
}
